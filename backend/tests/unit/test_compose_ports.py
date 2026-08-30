"""Regression tests for the host-port contracts in the Compose files."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_ENV = {
    "POSTGRES_PASSWORD": "compose-test-password",
    "SECRET_KEY": "compose-test-secret-key",
    "SHUAKE_COMPAT_SECRET": "",
    "CREDENTIAL_ENCRYPTION_KEY": "compose-test-fernet-key",
    "CORS_ORIGINS": '["http://localhost"]',
    "ENV": "dev",
}


def _compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "compose", "version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _compose_available(), reason="docker compose is required for Compose contract tests"
)


def _compose_config(
    tmp_path: Path,
    *compose_files: str,
    overrides: dict[str, str] | None = None,
) -> dict:
    env_values = dict(COMPOSE_ENV)
    env_values.update(overrides or {})
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in env_values.items()) + "\n",
        encoding="utf-8",
    )

    command = ["docker", "compose", "--env-file", str(env_file)]
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    command.extend(["-p", "uh-compose-port-tests", "config", "--format", "json"])

    process_env = os.environ.copy()
    # Keep interpolation controlled by the fixture rather than a developer's
    # shell or the repository's ignored .env file.
    for variable in (
        *COMPOSE_ENV,
        "APP_PORT",
        "HTTP_PORT",
        "HTTP_BIND_HOST",
        "UH_TAG",
        "COMPOSE_FILE",
        "COMPOSE_PROJECT_NAME",
    ):
        process_env.pop(variable, None)
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _published_ports(config: dict, service: str) -> set[tuple[str, str, int]]:
    return {
        (port.get("host_ip", ""), str(port["published"]), int(port["target"]))
        for port in config["services"][service]["ports"]
    }


def test_env_example_uses_the_active_release_web_port_name() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "HTTP_PORT=8080" in env_example
    assert "NGINX_PORT" not in env_example


def test_server_compose_uses_default_app_port(tmp_path: Path) -> None:
    config = _compose_config(tmp_path, "docker-compose.server.yml")

    assert _published_ports(config, "app") == {("127.0.0.1", "8000", 8000)}


def test_server_compose_uses_custom_app_port(tmp_path: Path) -> None:
    config = _compose_config(
        tmp_path,
        "docker-compose.server.yml",
        overrides={"APP_PORT": "9123"},
    )

    assert _published_ports(config, "app") == {("127.0.0.1", "9123", 8000)}


def test_release_compose_uses_http_port_for_web(tmp_path: Path) -> None:
    config = _compose_config(
        tmp_path,
        "docker-compose.release.yml",
        overrides={"HTTP_PORT": "19090"},
    )

    assert _published_ports(config, "app") == {("127.0.0.1", "8000", 8000)}
    assert _published_ports(config, "web") == {("127.0.0.1", "19090", 80)}


def test_release_compose_explicit_public_bind_host(tmp_path: Path) -> None:
    config = _compose_config(
        tmp_path,
        "docker-compose.release.yml",
        overrides={"HTTP_PORT": "19090", "HTTP_BIND_HOST": "0.0.0.0"},
    )

    assert _published_ports(config, "web") == {("0.0.0.0", "19090", 80)}


@pytest.mark.parametrize("overlay", ["docker-compose.staging.yml", "docker-compose.newhost.yml"])
def test_server_overlays_render_with_expected_host_ports(tmp_path: Path, overlay: str) -> None:
    config = _compose_config(tmp_path, "docker-compose.server.yml", overlay)

    assert {"app", "postgres"}.issubset(config["services"])
    if overlay == "docker-compose.staging.yml":
        # Compose merges the overlay's port entry with the base entry; retain
        # this check so changes to APP_PORT do not silently drop staging's
        # documented 8001 endpoint.
        assert ("127.0.0.1", "8001", 8000) in _published_ports(config, "app")
    else:
        assert _published_ports(config, "app") == {("127.0.0.1", "8000", 8000)}
        assert _published_ports(config, "web") == {("127.0.0.1", "18082", 80)}
