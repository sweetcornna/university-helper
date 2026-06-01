# Cookies management - simplified for unified platform
import json
import os
from pathlib import Path

# Persist cookies under a writable path. In production the container runs
# with a read-only rootfs (docker-compose.server.yml: read_only: true) and
# only /tmp is writable (tmpfs). A relative "cookies.json" resolves under the
# read-only code dir and fails with OSError [Errno 30] Read-only file system,
# which previously broke Chaoxing login and failed every learning task.
COOKIES_FILE = Path(os.environ.get("CHAOXING_COOKIES_FILE", "/tmp/cookies.json"))


def save_cookies(session):
    """Save session cookies to file.

    Best-effort: persisting cookies is an optimization, not a requirement, so
    a write failure must never propagate and break login.
    """
    try:
        cookies = session.cookies.get_dict()
        COOKIES_FILE.write_text(json.dumps(cookies))
    except OSError:
        pass


def use_cookies():
    """Load cookies from file. Returns {} if unavailable or unreadable."""
    try:
        if COOKIES_FILE.exists():
            return json.loads(COOKIES_FILE.read_text())
    except (OSError, ValueError):
        pass
    return {}
