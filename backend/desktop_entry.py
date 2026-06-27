"""Frozen desktop entrypoint for University Helper (the `uh-backend` sidecar).

Resolves an OS app-data dir, persists the local single-user secrets, points all
writable paths under app-data, sets PROFILE=local / STORAGE_BACKEND=sqlite (and
the rest) in os.environ BEFORE app.config is imported, picks a free loopback
port, prints the port token Tauri parses, then boots uvicorn with the asyncio
loop + h11 (NEVER uvloop — absent on Windows).

Helpers are kept side-effect-light and importable so the env/path wiring can be
unit-tested without starting uvicorn.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from collections.abc import Callable
from pathlib import Path

import platformdirs
from cryptography.fernet import Fernet

# ASCII identity (filesystem-safe). The display name 学道 lives Tauri-side only.
APP_NAME = "UniversityHelper"
APP_AUTHOR = "cornna"
TOKEN_PREFIX = "UH_BACKEND_LISTENING"


def app_data_dir() -> Path:
    """Return (creating if needed) the per-user app-data dir.

    Windows: %APPDATA%\\cornna\\UniversityHelper
    macOS:   ~/Library/Application Support/UniversityHelper
    Linux:   ~/.local/share/UniversityHelper
    """
    d = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def persisted(name: str, gen: Callable[[], str]) -> str:
    """Return a secret persisted under app-data, generating it once (mode 0600).

    First call: gen() produces the value, it is written + chmod 0600, returned.
    Later calls: the SAME stored value is read back, so SECRET_KEY / the Fernet
    key stay stable across restarts (otherwise previously-encrypted credentials
    would become undecryptable).
    """
    path = app_data_dir() / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = gen()
    path.write_text(value, encoding="utf-8")
    # 0600 is correct on POSIX (file holds a secret); a best-effort no-op on
    # Windows, which uses ACLs — swallow the OSError there.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def free_port() -> int:
    """Pick a currently-free loopback TCP port (bind :0, read it, close).

    There is an inherent TOCTOU window before uvicorn binds; acceptable for a
    single-user desktop app on loopback.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def frontend_dist() -> str:
    """Resolve the bundled frontend/dist dir (frozen via _MEIPASS, else repo path).

    Mirrors cxsecret_font.resource_path's _MEIPASS-first strategy so the same
    bundle works frozen and in dev (`python backend/desktop_entry.py`).
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend" / "dist")
    # backend/desktop_entry.py -> parents[1] == repo root -> frontend/dist
    candidates.append(Path(__file__).resolve().parents[1] / "frontend" / "dist")
    for c in candidates:
        if c.is_dir():
            return str(c)
    return str(candidates[0])  # stable fallback; SPA mount degrades if absent


def configure_env(port: int, dist: str) -> None:
    """Set every env var app.config needs — call BEFORE importing app.config/app.main.

    Idempotent w.r.t. the persisted secrets (read back, never regenerated).
    """
    d = app_data_dir()

    # Profile / storage selection (consumed by workstreams B / A).
    os.environ["PROFILE"] = "local"
    os.environ["STORAGE_BACKEND"] = "sqlite"
    os.environ["SQLITE_PATH"] = str(d / "local.db")
    os.environ["FRONTEND_DIST"] = dist  # consumed by workstream C

    # ENV=dev makes CREDENTIAL_ENCRYPTION_KEY optional in init_cipher and skips the
    # production https/CORS gate; ENFORCE_HTTPS=false stops the 301 loop on loopback.
    os.environ["ENV"] = "dev"
    os.environ["ENFORCE_HTTPS"] = "false"

    # Persisted secrets (satisfy config validators; stable across restarts).
    os.environ["SECRET_KEY"] = persisted("secret_key", lambda: secrets.token_urlsafe(48))
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = persisted("credential.key", lambda: Fernet.generate_key().decode("ascii"))

    # config.py parses CORS_ORIGINS as JSON; non-empty validator then passes.
    os.environ["CORS_ORIGINS"] = json.dumps([f"http://127.0.0.1:{port}"])

    # Writable runtime files under app-data (module defaults point at /tmp).
    os.environ["CHAOXING_COOKIES_FILE"] = str(d / "cookies.json")
    os.environ["CHAOXING_CACHE_FILE"] = str(d / "answer_cache.json")

    # NOTE: MAIN_DB_USER/MAIN_DB_PASSWORD are intentionally NOT seeded here.
    # Workstream A made them optional when STORAGE_BACKEND == "sqlite" (the
    # config model-validator only requires them for postgres), so the local
    # SQLite build boots without any Postgres credentials.


def main() -> None:
    # answer_base.py reads ./config.ini relative to CWD; chdir into app-data so an
    # optional user config.ini resolves and stray writes land in a writable dir.
    # The cookies/cache/sqlite paths set above are ABSOLUTE, so chdir is safe.
    os.chdir(app_data_dir())

    dist = frontend_dist()
    port = free_port()
    configure_env(port, dist)

    # The ONE line Tauri (workstream E) parses for the port. Printed BEFORE
    # uvicorn.run so the parent can navigate while the server finishes binding
    # (Tauri then polls /health). flush=True is mandatory — frozen stdout is
    # block-buffered.
    print(f"{TOKEN_PREFIX} {port}", flush=True)

    import uvicorn

    # Import string is resolved lazily inside run() — i.e. AFTER configure_env, so
    # app.config sees the local env. asyncio + h11 only (uvloop absent on Windows).
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        workers=1,
        loop="asyncio",
        http="h11",
        log_level="info",
    )


if __name__ == "__main__":
    main()
