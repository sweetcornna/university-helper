from fastapi.testclient import TestClient

from app.main import app


class _Probe:
    def __init__(self, ok):
        self._ok = ok

    def ping(self):
        return self._ok


class _Storage:
    def __init__(self, ok):
        self.tasks = None
        self.probe = _Probe(ok)


def test_health_ok_when_probe_true(monkeypatch):
    monkeypatch.setattr("app.main.get_storage", lambda: _Storage(True))
    r = TestClient(app, base_url="http://localhost").get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["status"] in {"ok", "degraded"}


def test_health_503_when_probe_false(monkeypatch):
    monkeypatch.setattr("app.main.get_storage", lambda: _Storage(False))
    r = TestClient(app, base_url="http://localhost").get("/health")
    assert r.status_code == 503
    assert r.json()["detail"] == "db unavailable"
