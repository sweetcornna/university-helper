"""Minimal /metrics endpoint (Prometheus exposition format).

Hand-rolled rather than depending on `prometheus-fastapi-instrumentator`
so we don't add a runtime dep for a basic counter surface. Swap to the
full library when real SLOs land.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Response

router = APIRouter()

_PROCESS_START = time.time()

# Counter is bounded:
#  - keys are the templated route ("/api/v1/users/{id}"), not raw paths, so
#    user IDs / task IDs don't explode cardinality.
#  - unmatched paths roll up to "_other_" so attackers can't blow the dict.
#  - a hard cap (_MAX_KEYS) is enforced on top for safety.
_MAX_KEYS = 2000
_UNMATCHED_KEY = "_other_"

_lock = threading.Lock()
_request_counter: dict[tuple[str, str], int] = {}


def _status_bucket(status_code: int) -> str:
    if status_code >= 500:
        return "5xx"
    if status_code >= 400:
        return "4xx"
    if status_code >= 300:
        return "3xx"
    return "2xx"


def record_request(route: str, status_code: int) -> None:
    """Bump the counter for a (route, status-bucket) pair.

    `route` should be a route *template* (e.g. ``"/api/v1/course/status/{task_id}"``),
    not a raw URL path — callers in middleware are responsible for resolving it.
    """
    key = (route or _UNMATCHED_KEY, _status_bucket(status_code))
    with _lock:
        if key in _request_counter:
            _request_counter[key] += 1
        elif len(_request_counter) < _MAX_KEYS:
            _request_counter[key] = 1
        else:
            # Capacity reached: bucket overflow into the "_other_" key so we
            # still get total throughput without unbounded growth.
            overflow = (_UNMATCHED_KEY, key[1])
            _request_counter[overflow] = _request_counter.get(overflow, 0) + 1


def _escape_label(value: str) -> str:
    # Prometheus exposition format escapes \, ", and \n in label values.
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def _render() -> str:
    lines: list[str] = [
        "# HELP uh_process_uptime_seconds Seconds since process start",
        "# TYPE uh_process_uptime_seconds gauge",
        f"uh_process_uptime_seconds {time.time() - _PROCESS_START:.2f}",
        "# HELP uh_requests_total HTTP requests grouped by route template and status bucket",
        "# TYPE uh_requests_total counter",
    ]
    with _lock:
        snapshot = list(_request_counter.items())
    for (route, bucket), count in snapshot:
        lines.append(
            f'uh_requests_total{{route="{_escape_label(route)}",status="{bucket}"}} {count}'
        )
    return "\n".join(lines) + "\n"


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=_render(), media_type="text/plain; version=0.0.4")
