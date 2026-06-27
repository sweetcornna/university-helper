"""Integration smoke test for the frozen sidecar (the per-OS CI gate).

Skipped unless UH_SIDECAR_BIN points at a built `uh-backend` binary, so the
normal unit run is unaffected. CI sets UH_SIDECAR_BIN after build_sidecar.sh and
runs: pytest tests/integration/test_sidecar_smoke.py
"""

import os
import re
import signal
import subprocess
import time
import urllib.request

import pytest

BIN = os.environ.get("UH_SIDECAR_BIN")

pytestmark = pytest.mark.skipif(
    not BIN or not os.path.exists(BIN),
    reason="UH_SIDECAR_BIN not set to a built sidecar binary",
)


def _start() -> subprocess.Popen:
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # own process group -> clean reap
    return subprocess.Popen(
        [BIN],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        **kwargs,
    )


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_sidecar_boots_and_health_ok():
    proc = _start()
    try:
        # 1) read the port token (90s budget; onefile cold-start unpacks ~35MB)
        port = None
        deadline = time.time() + 90
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    pytest.fail(f"sidecar exited early rc={proc.returncode}")
                continue
            m = re.match(r"UH_BACKEND_LISTENING (\d+)", line.strip())
            if m:
                port = int(m.group(1))
                break
        assert port, "never saw UH_BACKEND_LISTENING token"

        # 2) poll /health for 200 (60s budget)
        ok = False
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    if r.status == 200:
                        ok = True
                        break
            except Exception:
                time.sleep(0.2)
        assert ok, "/health never returned 200"
    finally:
        _kill(proc)
