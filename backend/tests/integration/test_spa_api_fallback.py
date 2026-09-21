"""Regression tests for API namespaces falling through an SPA mount."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import build_app


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>SPA</title>", encoding="utf-8")
    return dist


@pytest.fixture
def spa_client(tmp_path: Path):
    dist = _make_dist(tmp_path)
    with build_app("local", ENFORCE_HTTPS="false", FRONTEND_DIST=str(dist)) as app:
        yield TestClient(app, base_url="http://localhost")


@pytest.mark.parametrize("path", ["/api", "/api/v1/unknown", "/metrics/unknown"])
def test_unknown_api_namespaces_return_json_404(spa_client: TestClient, path: str) -> None:
    response = spa_client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert "application/json" in response.headers["content-type"]


def test_client_route_still_returns_spa_index(spa_client: TestClient) -> None:
    response = spa_client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text == "<!doctype html><title>SPA</title>"


def test_registered_api_route_still_wins(spa_client: TestClient) -> None:
    response = spa_client.get("/api/v1/chaoxing/location/geocode")

    assert response.status_code == 422
    assert "application/json" in response.headers["content-type"]
