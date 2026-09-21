from fastapi.testclient import TestClient

from tests.conftest import build_app


def test_runtime_profile_is_public_and_reports_server_policy():
    with build_app("server", ENFORCE_HTTPS="false") as app:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get("/api/v1/runtime")
    assert resp.status_code == 200
    assert resp.json() == {"profile": "server", "requires_auth": True}


def test_security_headers_allow_only_same_origin_geolocation():
    with build_app("server", ENFORCE_HTTPS="false") as app:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get("/api/v1/runtime")

    assert resp.status_code == 200
    assert resp.headers["Permissions-Policy"] == (
        "geolocation=(self), microphone=(), camera=(), payment=()"
    )


def test_runtime_profile_reports_local_without_exposing_settings():
    with build_app(
        "local",
        ENFORCE_HTTPS="false",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        resp = client.get("/api/v1/runtime")
    assert resp.status_code == 200
    assert resp.json() == {"profile": "local", "requires_auth": False}


def test_local_no_301_redirect_on_plain_http_loopback():
    # The env Workstream D injects for the desktop build (asserted here, not implemented):
    #   PROFILE=local, ENV=dev, STORAGE_BACKEND=sqlite,
    #   SECRET_KEY=<persisted >=32>, CORS_ORIGINS=["http://127.0.0.1:<port>"],
    #   ENFORCE_HTTPS=false   <-- without this the loopback webview would 301-loop.
    with build_app(
        "local",
        ENFORCE_HTTPS="false",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        # zhihuishu/status is a course.py route that needs no DB/external deps:
        # with B2's override it returns a clean 200 over plain http.
        resp = client.get("/api/v1/course/zhihuishu/status", follow_redirects=False)
    assert resp.status_code != 301
    assert resp.status_code == 200
    assert "location" not in {k.lower() for k in resp.headers}


def test_enforce_https_true_would_301_loop_the_loopback():
    # Documents WHY D must set ENFORCE_HTTPS=false: the default True 301-redirects
    # every plain-http loopback request to https:// (which the webview can't reach).
    with build_app(
        "local",
        ENFORCE_HTTPS="true",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        resp = client.get("/health", follow_redirects=False)  # public route
    assert resp.status_code == 301
    assert resp.headers["location"].startswith("https://")


def test_loopback_host_accepted_by_trustedhost():
    # CORS_ORIGINS=["http://127.0.0.1:<port>"] feeds _build_allowed_hosts (main.py:81),
    # and 127.0.0.1 is always seeded -> the loopback Host header is not a 400.
    with build_app(
        "local",
        ENFORCE_HTTPS="false",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        resp = client.get("/api/v1/course/zhihuishu/status", follow_redirects=False)
    assert resp.status_code != 400  # not "Invalid host header"


def test_allowed_hosts_setting_admits_lan_ip_and_wildcard_domain():
    with build_app("server", ENFORCE_HTTPS="false", ALLOWED_HOSTS="192.168.1.10, *.uh.lan") as app:
        client = TestClient(app, raise_server_exceptions=False)
        lan = client.get("/api/v1/runtime", headers={"host": "192.168.1.10:8080"})
        wildcard = client.get("/api/v1/runtime", headers={"host": "school.uh.lan"})
        rejected = client.get("/api/v1/runtime", headers={"host": "evil.test"})

    assert lan.status_code == 200
    assert wildcard.status_code == 200
    assert rejected.status_code == 400
    body = rejected.json()
    assert body["code"] == "InvalidHost"
    assert "ALLOWED_HOSTS" in body["message"]
    assert "Invalid host header" in body["message"]


def test_wildcard_allowed_hosts_rejected_in_production():
    with build_app("server", ENFORCE_HTTPS="false", ALLOWED_HOSTS="*", ENV="production", CORS_ORIGINS='["https://uh.example.com"]'):
        import app.main as main_mod

        try:
            main_mod._validate_runtime_settings()
        except RuntimeError as exc:
            assert "ALLOWED_HOSTS" in str(exc)
        else:  # pragma: no cover - assertion path
            raise AssertionError("production must reject ALLOWED_HOSTS='*'")
