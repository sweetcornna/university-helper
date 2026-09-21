"""Frozen desktop entrypoint for University Helper (the `uh-backend` sidecar).

Resolves an OS app-data dir, persists the local single-user secrets, points all
writable paths under app-data, sets PROFILE=local / STORAGE_BACKEND=sqlite (and
the rest) in os.environ BEFORE app.config is imported, picks a free loopback
port, imports the ASGI app, prints the port token Tauri parses, then boots
uvicorn with the asyncio loop + h11 (NEVER uvloop — absent on Windows).

Helpers are kept side-effect-light and importable so the env/path wiring can be
unit-tested without starting uvicorn.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import platformdirs
from cryptography.fernet import Fernet

# ASCII identity (filesystem-safe). The display name 学道 lives Tauri-side only.
APP_NAME = "UniversityHelper"
APP_AUTHOR = "cornna"
TOKEN_PREFIX = "UH_BACKEND_LISTENING"
# Set by the Tauri shell: the desktop process that owns this backend.
PARENT_PID_ENV = "UH_PARENT_PID"
PID_FILE_NAME = "uh-backend.pid"
SIDECAR_NAME = "uh-backend"


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


# ---- process lifetime -------------------------------------------------------
#
# The sidecar is a PyInstaller --onefile build: a small bootloader process starts
# the real Python process as its child. When the desktop shell stops the sidecar
# it can only kill the bootloader, which does not take the Python child with it
# (SIGKILL cannot be forwarded; Windows has no job object here). Without the
# guards below every quit or update left a backend running on its old port,
# holding local.db and still executing background tasks.


def pid_alive(pid: int) -> bool:
    """True when a process with this PID exists. Never signals the process."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        query_limited = 0x1000
        wait_timeout = 0x102
        error_access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(synchronize | query_limited, False, pid)
        if not handle:
            return ctypes.get_last_error() == error_access_denied
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    # os.kill(pid, 0) only probes on POSIX (on Windows it would terminate).
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _exit_now() -> None:
    os._exit(0)


def _graceful_exit() -> None:
    """Ask uvicorn to shut down; force the exit if it has not after 5 s."""
    if sys.platform == "win32":
        _exit_now()
        return
    timer = threading.Timer(5.0, _exit_now)
    timer.daemon = True
    timer.start()
    os.kill(os.getpid(), signal.SIGTERM)


def is_orphaned(parent_pid: int | None, initial_ppid: int, current_ppid: int) -> bool:
    if parent_pid is not None and not pid_alive(parent_pid):
        return True
    if sys.platform != "win32" and current_ppid != initial_ppid:
        return True  # the bootloader died and we were re-parented
    return initial_ppid > 1 and not pid_alive(initial_ppid)


def start_parent_watchdog(
    parent_pid: int | None,
    poll_seconds: float = 1.0,
    on_orphan: Callable[[], None] = _graceful_exit,
) -> threading.Thread:
    initial_ppid = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(poll_seconds)
            if is_orphaned(parent_pid, initial_ppid, os.getppid()):
                on_orphan()
                return

    thread = threading.Thread(target=watch, name="uh-parent-watchdog", daemon=True)
    thread.start()
    return thread


def _process_image(pid: int) -> str:
    """Best-effort executable path/name of a process ('' when unknown)."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return ""
            try:
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    return buffer.value
                return ""
            finally:
                kernel32.CloseHandle(handle)
        if sys.platform.startswith("linux"):
            return os.readlink(f"/proc/{pid}/exe")
        result = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _is_sidecar_image(image: str) -> bool:
    name = Path(image.replace("\\", "/")).name.lower()
    return name in {SIDECAR_NAME, f"{SIDECAR_NAME}.exe"}


def _terminate(pid: int) -> None:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            try:
                kernel32.TerminateProcess(handle, 0)
            finally:
                kernel32.CloseHandle(handle)
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not pid_alive(pid):
                return
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def reap_stale_backend(pid_file: Path) -> bool:
    """Stop a backend left behind by a previous run. Returns True if one was stopped.

    Only a process recorded in our PID file, still alive, whose desktop parent is
    gone and whose executable is the sidecar, is terminated.
    """
    try:
        record = json.loads(pid_file.read_text(encoding="utf-8"))
        pid = int(record["pid"])
        parent = record.get("parent_pid")
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if pid == os.getpid() or not pid_alive(pid):
        return False
    if parent is not None and pid_alive(int(parent)):
        return False  # another running desktop instance still owns it
    if not _is_sidecar_image(_process_image(pid)):
        return False
    _terminate(pid)
    return True


def reap_orphaned_sidecars() -> list[int]:
    """POSIX: stop sidecar processes re-parented to init (left over by 1.4.x)."""
    if sys.platform == "win32":
        return []
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    stopped: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        pid, ppid, command = int(parts[0]), int(parts[1]), parts[2]
        if ppid == 1 and pid != os.getpid() and _is_sidecar_image(command):
            _terminate(pid)
            stopped.append(pid)
    return stopped


def write_pid_file(pid_file: Path, parent_pid: int | None) -> None:
    try:
        pid_file.write_text(json.dumps({"pid": os.getpid(), "parent_pid": parent_pid}), encoding="utf-8")
    except OSError:
        pass


def parent_pid_from_env() -> int | None:
    raw = os.environ.get(PARENT_PID_ENV, "").strip()
    return int(raw) if raw.isdigit() else None


def guard_process_lifetime() -> None:
    """Clean up earlier backends, then exit whenever the desktop shell goes away."""
    parent_pid = parent_pid_from_env()
    if parent_pid is None and not getattr(sys, "frozen", False):
        return  # plain `python desktop_entry.py` during development
    pid_file = app_data_dir() / PID_FILE_NAME
    reap_stale_backend(pid_file)
    if getattr(sys, "frozen", False):
        reap_orphaned_sidecars()
    write_pid_file(pid_file, parent_pid)
    if parent_pid is not None:
        start_parent_watchdog(parent_pid)


def main() -> None:
    # answer_base.py reads ./config.ini relative to CWD; chdir into app-data so an
    # optional user config.ini resolves and stray writes land in a writable dir.
    # The cookies/cache/sqlite paths set above are ABSOLUTE, so chdir is safe.
    os.chdir(app_data_dir())
    guard_process_lifetime()

    dist = frontend_dist()
    port = free_port()
    configure_env(port, dist)

    import uvicorn

    # Import the ASGI app OBJECT, not uvicorn's "app.main:app" import string: the
    # frozen PyInstaller importer does not resolve that lazy string import (it
    # raises ModuleNotFoundError: app at runtime). Importing it directly here —
    # AFTER configure_env, so app.config reads the local env — bundles it as a
    # real dependency and hands uvicorn the object (workers=1 needs no string).
    # asyncio + h11 only (uvloop absent on Windows).
    from app.main import app as fastapi_app

    # The ONE line Tauri (workstream E) parses for the port. Emit it only after
    # the heavy app import above has completed; frozen onefile imports can take
    # tens of seconds on a cold start, and Tauri's post-token socket wait should
    # cover uvicorn binding rather than Python module import time.
    # flush=True is mandatory — frozen stdout is block-buffered.
    print(f"{TOKEN_PREFIX} {port}", flush=True)

    uvicorn.run(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        workers=1,
        loop="asyncio",
        http="h11",
        log_level="info",
    )


if __name__ == "__main__":
    main()
