import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class RateLimiter:
    MAX_CACHE_SIZE = 10000
    CLEANUP_INTERVAL = 100  # Run cleanup every N requests
    DB_CLEANUP_INTERVAL = 500  # Sweep stale DB rows every N requests

    def __init__(self, requests: int = 5, window: int = 60):
        self.requests = requests
        self.window = window
        self._cache: dict[str, tuple[int, datetime]] = defaultdict(lambda: (0, datetime.now()))
        self._request_count: int = 0
        # check_rate_limit is now invoked via asyncio.to_thread (off the event
        # loop), so concurrent threads can touch _cache / _request_count at once.
        # Guard every mutation of that shared state to avoid lost counts and
        # "dict changed size during iteration" in the cleanup sweep.
        self._lock = threading.Lock()

    def _is_trusted_proxy(self, host: str) -> bool:
        candidate = str(host or "").strip()
        if not candidate:
            return False
        if candidate.lower() == "localhost":
            return True

        try:
            parsed = ip_address(candidate)
        except ValueError:
            return False

        return parsed.is_private or parsed.is_loopback or parsed.is_link_local

    def _cleanup_expired(self) -> None:
        """Remove expired entries to prevent unbounded memory growth."""
        now = datetime.now()
        expired_keys = [
            key for key, (_, start_time) in self._cache.items() if now - start_time > timedelta(seconds=self.window)
        ]
        for key in expired_keys:
            del self._cache[key]

    def _evict_oldest(self) -> None:
        """Evict oldest entries when cache exceeds MAX_CACHE_SIZE."""
        if len(self._cache) <= self.MAX_CACHE_SIZE:
            return
        # Sort by start_time (oldest first) and remove excess entries
        sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][1])
        evict_count = len(self._cache) - self.MAX_CACHE_SIZE
        for key in sorted_keys[:evict_count]:
            del self._cache[key]

    def _maybe_cleanup(self) -> None:
        """Periodically clean up expired and excess entries."""
        with self._lock:
            self._request_count += 1
            if self._request_count % self.CLEANUP_INTERVAL == 0:
                self._cleanup_expired()
                self._evict_oldest()

    def _get_forwarded_client_id(self, request: Request) -> str | None:
        # X-Forwarded-For is only consulted when the direct peer is a known
        # private/loopback proxy (see _is_trusted_proxy). nginx forwards
        # `X-Forwarded-For $proxy_add_x_forwarded_for`, which APPENDS the real
        # peer IP rather than overwriting the header, so the chain looks like
        # `<client-supplied...>, <real-client>, <nginx hop>, ...`.
        #
        # We therefore walk the chain RIGHT-TO-LEFT and skip trusted-proxy
        # entries, returning the RIGHTMOST UNTRUSTED hop — the real client as
        # seen by our infrastructure. Returning the leftmost entry (as before)
        # would let a client spoof `X-Forwarded-For: 1.2.3.4` and rotate the
        # spoofed value to dodge the limiter.
        forwarded_for = str(request.headers.get("x-forwarded-for") or "").strip()
        if forwarded_for:
            for part in reversed(forwarded_for.split(",")):
                candidate = part.strip()
                if not candidate:
                    continue
                if self._is_trusted_proxy(candidate):
                    # A trusted infra hop (our nginx / private network). Keep
                    # walking left toward the real client.
                    continue
                return candidate

        # x-real-ip is set by nginx itself (single value, not client-appendable
        # through the proxy_add chain), so it is safe to use as a fallback.
        real_ip = str(request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip

        return None

    def _get_client_id(self, request: Request) -> str:
        client_host = request.client.host if request.client else ""

        if self._is_trusted_proxy(client_host):
            forwarded_client_id = self._get_forwarded_client_id(request)
            if forwarded_client_id:
                return forwarded_client_id

        return client_host or "unknown"

    def reset(self) -> None:
        self._cache.clear()

    def _current_window_start(self, now: datetime) -> datetime:
        """Floor `now` to the current window boundary in UTC."""
        aware = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
        bucket = int(aware.timestamp()) // self.window * self.window
        return datetime.fromtimestamp(bucket, tz=UTC)

    def _check_via_db(self, client_id: str, now: datetime) -> bool | None:
        """Atomically increment counter in Postgres for the current window.

        Returns True if allowed, False if limit exceeded, or None if the DB
        path is unavailable (caller should fall back to in-memory).
        """
        try:
            from app.db.session import get_db_session
        except Exception as exc:  # pragma: no cover - import guard
            logger.debug("rate_limiter: DB session module unavailable (%s)", exc)
            return None

        window_start = self._current_window_start(now)
        try:
            with get_db_session() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rate_limit_counters (client_id, window_start, count)
                        VALUES (%s, %s, 1)
                        ON CONFLICT (client_id, window_start)
                        DO UPDATE SET count = rate_limit_counters.count + 1
                        RETURNING count
                        """,
                        (client_id, window_start),
                    )
                    row = cur.fetchone()
                    # RealDictCursor returns a dict; plain cursor returns a tuple.
                    new_count = row["count"] if isinstance(row, dict) else row[0]

                    if self._request_count % self.DB_CLEANUP_INTERVAL == 0:
                        cur.execute(
                            "DELETE FROM rate_limit_counters " "WHERE window_start < %s",
                            (window_start - timedelta(seconds=self.window * 2),),
                        )
            return new_count <= self.requests
        except Exception as exc:
            logger.warning("rate_limiter: DB path failed, falling back to in-memory (%s)", exc)
            return None

    def _check_in_memory(self, client_id: str, now: datetime) -> bool:
        """In-memory fallback. Returns True if allowed, False if blocked."""
        with self._lock:
            count, start_time = self._cache[client_id]

            if now - start_time > timedelta(seconds=self.window):
                self._cache[client_id] = (1, now)
                return True

            if count >= self.requests:
                return False

            self._cache[client_id] = (count + 1, start_time)
            return True

    def check_rate_limit(self, request: Request) -> None:
        self._maybe_cleanup()
        client_id = self._get_client_id(request)
        now = datetime.now()

        db_result = self._check_via_db(client_id, now)
        if db_result is None:
            allowed = self._check_in_memory(client_id, now)
        else:
            allowed = db_result

        if not allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")


rate_limiter = RateLimiter()
