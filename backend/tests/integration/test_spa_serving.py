import importlib

import pytest
from fastapi.testclient import TestClient


def _reload_app_with_dist(monkeypatch, frontend_dist: str):
    """Rebuild app.main with FRONTEND_DIST = frontend_dist.

    SPA wiring (root() branch, /assets mount, catch-all) is decided at import
    time from the resolved dist dir, so the module must be reloaded after the
    env is set. config is reloaded first so app.main re-binds the new settings.
    """
    monkeypatch.setenv("FRONTEND_DIST", frontend_dist)
    config_mod = importlib.import_module("app.config")
    importlib.reload(config_mod)
    main_mod = importlib.import_module("app.main")
    importlib.reload(main_mod)
    return main_mod


def _make_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>SPA</title><div id=root></div>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("console.log('app');", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


@pytest.fixture
def spa_client(monkeypatch, tmp_path):
    """TestClient bound to an app that serves a temp SPA dist."""
    dist = _make_dist(tmp_path)
    main_mod = _reload_app_with_dist(monkeypatch, str(dist))
    # No context manager: match conftest's client fixture so lifespan (DB probe,
    # cleanup loop) does not run for these routing-only tests.
    client = TestClient(main_mod.app, base_url="http://localhost")
    client._uh_dist = dist  # stash for assertions
    yield client
    # Restore the pristine default module for later test files.
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    importlib.reload(importlib.import_module("app.config"))
    importlib.reload(importlib.import_module("app.main"))


@pytest.fixture
def no_dist_client(monkeypatch, tmp_path):
    """TestClient bound to an app with NO servable dist (server behavior)."""
    main_mod = _reload_app_with_dist(monkeypatch, str(tmp_path / "does-not-exist"))
    client = TestClient(main_mod.app, base_url="http://localhost")
    yield client
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    importlib.reload(importlib.import_module("app.config"))
    importlib.reload(importlib.import_module("app.main"))


def test_root_serves_index_when_dist_present(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text == (spa_client._uh_dist / "index.html").read_text(encoding="utf-8")


def test_root_returns_json_when_no_dist(no_dist_client):
    # Server behavior preserved: no dist -> the original JSON body.
    resp = no_dist_client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "University Helper API"}
