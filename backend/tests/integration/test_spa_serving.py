import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient


def _reload_app_with_dist(monkeypatch, frontend_dist: str):
    """Rebuild app.main with FRONTEND_DIST = frontend_dist.

    SPA wiring (root() branch, /assets mount, catch-all) is decided at import
    time from the resolved dist dir, so the module must be reloaded after the
    env is set. config is reloaded first so app.main re-binds the new settings.

    Same-origin SPA serving is a PROFILE=local feature: the desktop build never
    logs in, so the tenant_isolation JWT gate is OFF (workstream B). In server
    profile that gate would 401 every non-public static/SPA path before routing,
    so these routing tests run under PROFILE=local to mirror real desktop use.
    """
    monkeypatch.setenv("PROFILE", "local")
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
    monkeypatch.delenv("PROFILE", raising=False)
    importlib.reload(importlib.import_module("app.config"))
    importlib.reload(importlib.import_module("app.main"))


@pytest.fixture
def no_dist_client(monkeypatch, tmp_path):
    """TestClient bound to an app with NO servable dist (server behavior)."""
    main_mod = _reload_app_with_dist(monkeypatch, str(tmp_path / "does-not-exist"))
    client = TestClient(main_mod.app, base_url="http://localhost")
    yield client
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    monkeypatch.delenv("PROFILE", raising=False)
    importlib.reload(importlib.import_module("app.config"))
    importlib.reload(importlib.import_module("app.main"))


def test_root_serves_index_when_dist_present(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text == (spa_client._uh_dist / "index.html").read_text(encoding="utf-8")


def test_spa_html_csp_allows_bundled_assets(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    csp = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'none'" not in csp


def test_api_json_keeps_strict_csp(spa_client):
    resp = spa_client.get("/health")
    assert resp.status_code in (200, 503)
    assert resp.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


def test_root_returns_json_when_no_dist(no_dist_client):
    # Server behavior preserved: no dist -> the original JSON body.
    resp = no_dist_client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "University Helper API"}


def test_client_route_returns_index(spa_client):
    # An unknown, non-file path is a client-side route -> SPA shell.
    resp = spa_client.get("/dashboard/courses")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text == (spa_client._uh_dist / "index.html").read_text(encoding="utf-8")


def test_hashed_asset_served_with_bytes(spa_client):
    resp = spa_client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('app');"
    # Served as a real JS asset, not the HTML shell.
    assert "text/html" not in resp.headers["content-type"]


def test_top_level_static_file_served(spa_client):
    # Files directly under dist (favicon.svg, sw.js, robots.txt ...) go through the
    # catch-all, not /assets, and must be returned as real files.
    resp = spa_client.get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.text == "<svg/>"


def test_api_route_still_wins_over_catch_all(spa_client):
    # Required `query` missing -> FastAPI 422 BEFORE the handler (no DB/auth/network).
    # Proves the API router claims the path instead of the SPA catch-all.
    resp = spa_client.get("/api/v1/chaoxing/location/geocode")
    assert resp.status_code == 422
    assert "application/json" in resp.headers["content-type"]


def test_health_route_still_wins_over_catch_all(spa_client):
    # /health is a GET FULL-match route registered before the catch-all; with no
    # DB it 503s -- either way it is NOT the 200 HTML shell.
    resp = spa_client.get("/health")
    assert resp.status_code in (200, 503)
    assert "text/html" not in resp.headers.get("content-type", "")


def test_path_traversal_is_blocked(spa_client, monkeypatch):
    # HTTP clients normalize '..', so exercise the guard by calling the route
    # coroutine directly with a raw traversal path. It must fall back to index.html
    # rather than returning an out-of-tree file.
    import app.main as main_mod

    importlib.reload(importlib.import_module("app.config"))
    # spa_client already reloaded main with the temp dist; grab its route fn.
    spa_fn = None
    for route in main_mod.app.router.routes:
        if getattr(route, "name", "") == "spa":
            spa_fn = route.endpoint
            break
    assert spa_fn is not None, "spa catch-all route not registered"
    result = asyncio.run(spa_fn("../../etc/passwd"))
    # FileResponse for index.html, never /etc/passwd.
    assert str(result.path).endswith("index.html")


def test_no_catch_all_registered_without_dist(no_dist_client):
    # With no dist, an unknown GET path must 404 (no catch-all) -> server unchanged.
    resp = no_dist_client.get("/some/client/route")
    assert resp.status_code == 404
