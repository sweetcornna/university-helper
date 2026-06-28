import json
import os
import socket
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import desktop_entry  # backend/ is on sys.path (same as `import app`)


@pytest.fixture(autouse=True)
def _restore_environ():
    # configure_env() mutates the real os.environ (PROFILE/STORAGE_BACKEND/...);
    # snapshot + restore so those values cannot leak into later tests that reload
    # app.config under a different profile.
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    # Redirect every app_data_dir() call (configure_env + persisted use the
    # module global) to an isolated tmp dir.
    monkeypatch.setattr(desktop_entry, "app_data_dir", lambda: tmp_path)
    return tmp_path


def test_free_port_returns_bindable_port():
    port = desktop_entry.free_port()
    assert 1024 < port < 65536
    # It was free at selection time -> we can bind it now.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_persisted_generates_once_then_returns_same(appdata):
    calls = {"n": 0}

    def gen():
        calls["n"] += 1
        return f"value-{calls['n']}"

    first = desktop_entry.persisted("secret_key", gen)
    second = desktop_entry.persisted("secret_key", gen)
    assert first == second == "value-1"
    assert calls["n"] == 1  # gen() ran exactly once


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode bits")
def test_persisted_writes_0600(appdata):
    desktop_entry.persisted("credential.key", lambda: "k")
    mode = stat.S_IMODE((appdata / "credential.key").stat().st_mode)
    assert mode == 0o600


def test_configure_env_sets_every_required_var(appdata, monkeypatch):
    for k in (
        "PROFILE STORAGE_BACKEND SQLITE_PATH FRONTEND_DIST ENV ENFORCE_HTTPS "
        "SECRET_KEY CREDENTIAL_ENCRYPTION_KEY CORS_ORIGINS "
        "CHAOXING_COOKIES_FILE CHAOXING_CACHE_FILE MAIN_DB_USER MAIN_DB_PASSWORD"
    ).split():
        monkeypatch.delenv(k, raising=False)

    desktop_entry.configure_env(54321, "/some/dist")

    assert os.environ["PROFILE"] == "local"
    assert os.environ["STORAGE_BACKEND"] == "sqlite"
    assert os.environ["ENV"] == "dev"
    assert os.environ["ENFORCE_HTTPS"] == "false"
    assert os.environ["FRONTEND_DIST"] == "/some/dist"
    assert os.environ["SQLITE_PATH"] == str(appdata / "local.db")
    assert os.environ["CHAOXING_COOKIES_FILE"] == str(appdata / "cookies.json")
    assert os.environ["CHAOXING_CACHE_FILE"] == str(appdata / "answer_cache.json")
    # CORS_ORIGINS must be a JSON list with exactly the loopback origin.
    assert json.loads(os.environ["CORS_ORIGINS"]) == ["http://127.0.0.1:54321"]
    assert len(os.environ["SECRET_KEY"]) >= 16
    # CREDENTIAL_ENCRYPTION_KEY must be a usable Fernet key.
    from cryptography.fernet import Fernet

    Fernet(os.environ["CREDENTIAL_ENCRYPTION_KEY"].encode())


def test_configure_env_secrets_stable_across_calls(appdata):
    desktop_entry.configure_env(1111, "/d")
    sk1, ck1 = os.environ["SECRET_KEY"], os.environ["CREDENTIAL_ENCRYPTION_KEY"]
    desktop_entry.configure_env(2222, "/d")  # different port, same persisted secrets
    assert os.environ["SECRET_KEY"] == sk1
    assert os.environ["CREDENTIAL_ENCRYPTION_KEY"] == ck1


def test_app_config_imports_after_configure_env(tmp_path):
    # Run in a clean subprocess: proves configure_env ALONE satisfies app.config's
    # import-time validators, without mutating this session's os.environ/sys.modules
    # and without inheriting pytest.ini's env. (`settings = Settings()` runs at import.)
    code = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        for k in ("SECRET_KEY CORS_ORIGINS ENFORCE_HTTPS ENV PROFILE STORAGE_BACKEND "
                  "SQLITE_PATH FRONTEND_DIST CREDENTIAL_ENCRYPTION_KEY MAIN_DB_USER "
                  "MAIN_DB_PASSWORD CHAOXING_COOKIES_FILE CHAOXING_CACHE_FILE").split():
            os.environ.pop(k, None)
        import desktop_entry
        desktop_entry.app_data_dir = lambda: Path(sys.argv[1])
        desktop_entry.configure_env(45678, "/d")
        from app.config import settings
        assert settings.CORS_ORIGINS == ["http://127.0.0.1:45678"], settings.CORS_ORIGINS
        assert settings.ENFORCE_HTTPS is False
        assert len(settings.SECRET_KEY) >= 16
        assert os.environ["PROFILE"] == "local"
        # PROFILE typed field arrives with workstream B (extra='ignore' drops it until then).
        if hasattr(settings, "PROFILE"):
            assert settings.PROFILE == "local"
        print("OK")
        """
    )
    backend = Path(desktop_entry.__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=str(backend),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_readiness_token_is_emitted_after_heavy_app_import():
    source = Path(desktop_entry.__file__).read_text(encoding="utf-8")

    app_import = source.index("from app.main import app as fastapi_app")
    readiness_print = source.index('print(f"{TOKEN_PREFIX} {port}"')

    assert app_import < readiness_print
