"""Regression tests for the release stack's public HTTP bind contract."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASH_DEPLOY = REPO_ROOT / "scripts" / "deploy_server.sh"
POWERSHELL_DEPLOY = REPO_ROOT / "scripts" / "deploy_server.ps1"
COMPOSE_FILE = REPO_ROOT / "docker-compose.release.yml"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _bash_deploy_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / "deploy"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(BASH_DEPLOY, scripts / BASH_DEPLOY.name)
    shutil.copy2(COMPOSE_FILE, root / COMPOSE_FILE.name)
    shutil.copytree(REPO_ROOT / "database", root / "database")

    bin_dir = root / "bin"
    bin_dir.mkdir()
    docker_log = root / "docker.log"
    _write_executable(
        bin_dir / "docker",
        f"""
        #!/usr/bin/env bash
        printf '%s HTTP_BIND_HOST=%s\\n' "$*" "${{HTTP_BIND_HOST:-}}" >> "{docker_log}"
        if [[ "$1" == "--version" ]]; then
          echo "Docker version 29.4.1, build test"
          exit 0
        fi
        if [[ "$1" == "info" ]]; then
          exit 0
        fi
        if [[ "$1" == "compose" && "$2" == "version" ]]; then
          echo "Docker Compose version v2.32.0"
          exit 0
        fi
        if [[ "$1" == "compose" ]]; then
          exit 0
        fi
        exit 1
        """,
    )
    _write_executable(
        bin_dir / "curl",
        """
        #!/usr/bin/env bash
        printf '200'
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return root, env, docker_log


@pytest.mark.parametrize(
    ("args", "expected_bind"),
    [
        (("-y", "--no-tls"), "127.0.0.1"),
        (("--domain", "example.test", "-y", "--no-tls"), "127.0.0.1"),
        (("--host", "203.0.113.10", "-y", "--no-tls"), "0.0.0.0"),
    ],
)
def test_bash_deploy_persists_and_passes_expected_http_bind_host(tmp_path, args, expected_bind):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    up_lines = [line for line in docker_log.read_text().splitlines() if " up -d " in f" {line} "]
    assert len(up_lines) == 1
    assert f"HTTP_BIND_HOST={expected_bind}" in up_lines[0]
    env_path = root / ".env"
    assert f"HTTP_BIND_HOST={expected_bind}\n" in env_path.read_text()
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "domain",
    [
        "../../nginx/nginx",
        "example\n.com",
        "example..com",
        "-example.com",
        "example-.com",
        "a" * 64 + ".example.com",
        ".".join(["a" * 63] * 4),
        "example_com",
        "",
    ],
    ids=[
        "path-traversal",
        "control-character",
        "empty-label",
        "leading-hyphen",
        "trailing-hyphen",
        "label-too-long",
        "domain-too-long",
        "invalid-character",
        "empty-domain",
    ],
)
def test_bash_deploy_rejects_invalid_domain_before_side_effects(tmp_path, domain):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    target = root / "nginx" / "nginx.conf"
    target.parent.mkdir()
    original = "keep this configuration\n"
    target.write_text(original, encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain", domain, "-y"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid --domain" in result.stderr
    if domain:
        assert domain not in result.stderr
    assert not docker_log.exists()
    assert not (root / "deploy").exists()
    assert not (root / ".env").exists()
    assert target.read_text(encoding="utf-8") == original


def test_bash_deploy_rejects_missing_domain_value_before_side_effects(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid --domain" in result.stderr
    assert not docker_log.exists()
    assert not (root / "deploy").exists()
    assert not (root / ".env").exists()


@pytest.mark.parametrize("domain", ["example.com", "sub.example.com", "xn--fiqs8s.com"])
def test_bash_deploy_accepts_ascii_and_punycode_fqdns(tmp_path, domain):
    root, env, _ = _bash_deploy_fixture(tmp_path)
    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain", domain, "-y", "--no-tls"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f'CORS_ORIGINS=["https://{domain}"]' in (root / ".env").read_text(encoding="utf-8")


VALID_FERNET = "A" * 43 + "="


def _run_bash(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/deploy_server.sh", *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def _up_line(docker_log: Path) -> str:
    up_lines = [line for line in docker_log.read_text().splitlines() if " up -d " in f" {line} "]
    assert len(up_lines) == 1
    return up_lines[0]


def test_bash_redeploy_keeps_secrets_and_applies_explicit_flags(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    env_path = root / ".env"
    secret = "s" * 64
    env_path.write_text(
        f"POSTGRES_PASSWORD=dbpass\nSECRET_KEY={secret}\nCREDENTIAL_ENCRYPTION_KEY={VALID_FERNET}\n"
        'CORS_ORIGINS=["http://203.0.113.10:8080"]\nENV=dev\nHTTP_BIND_HOST=0.0.0.0\nHTTP_PORT=8080\n',
        encoding="utf-8",
    )
    env_path.chmod(0o640)

    result = _run_bash(root, env, "--domain", "example.test", "--admin-email", "Ops@Example.test", "-y", "--no-tls")

    assert result.returncode == 0, result.stdout + result.stderr
    values = _env_values(env_path)
    assert values["POSTGRES_PASSWORD"] == "dbpass"
    assert values["SECRET_KEY"] == secret
    assert values["CREDENTIAL_ENCRYPTION_KEY"] == VALID_FERNET
    assert values["CORS_ORIGINS"] == '["https://example.test"]'
    assert values["ENV"] == "production"
    assert values["HTTP_BIND_HOST"] == "127.0.0.1"
    assert values["ADMIN_EMAILS"] == "Ops@Example.test"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o640
    assert "HTTP_BIND_HOST=127.0.0.1" in _up_line(docker_log)


def test_bash_redeploy_without_flags_keeps_network_settings(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    env_path = root / ".env"
    env_path.write_text(
        f"POSTGRES_PASSWORD=dbpass\nSECRET_KEY={'s' * 64}\nCREDENTIAL_ENCRYPTION_KEY={VALID_FERNET}\n"
        'CORS_ORIGINS=["http://203.0.113.10:9090"]\nENV=dev\nHTTP_BIND_HOST=0.0.0.0\nHTTP_PORT=9090\n',
        encoding="utf-8",
    )

    result = _run_bash(root, env, "--tag", "1.4.7", "-y")

    assert result.returncode == 0, result.stdout + result.stderr
    values = _env_values(env_path)
    assert values["HTTP_BIND_HOST"] == "0.0.0.0"
    assert values["HTTP_PORT"] == "9090"
    assert values["CORS_ORIGINS"] == '["http://203.0.113.10:9090"]'
    up_line = _up_line(docker_log)
    assert "HTTP_BIND_HOST=0.0.0.0" in up_line


def test_bash_fills_example_env_placeholders(tmp_path):
    root, env, _ = _bash_deploy_fixture(tmp_path)
    env_path = root / ".env"
    shutil.copy2(REPO_ROOT / ".env.example", env_path)

    result = _run_bash(root, env, "-y", "--no-tls")

    assert result.returncode == 0, result.stdout + result.stderr
    values = _env_values(env_path)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}=", values["CREDENTIAL_ENCRYPTION_KEY"])
    assert not values["SECRET_KEY"].startswith("change-this")
    assert len(values["SECRET_KEY"]) >= 32
    assert not values["POSTGRES_PASSWORD"].startswith("change-this")


def test_bash_rejects_malformed_credential_key(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    (root / ".env").write_text(
        f"POSTGRES_PASSWORD=dbpass\nSECRET_KEY={'s' * 64}\nCREDENTIAL_ENCRYPTION_KEY=not-a-key\n", encoding="utf-8"
    )

    result = _run_bash(root, env, "-y")

    assert result.returncode != 0
    assert "not a valid Fernet key" in result.stderr
    assert " up -d" not in (docker_log.read_text() if docker_log.exists() else "")


def _mark_volume_present(root: Path) -> None:
    docker = root / "bin" / "docker"
    source = docker.read_text(encoding="utf-8")
    docker.write_text(
        source.replace(
            'if [[ "$1" == "info" ]]; then',
            'if [[ "$1" == "volume" && "$2" == "inspect" ]]; then\n  exit 0\nfi\nif [[ "$1" == "info" ]]; then',
            1,
        ),
        encoding="utf-8",
    )


def test_bash_refuses_new_secrets_when_database_volume_exists(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    _mark_volume_present(root)

    result = _run_bash(root, env, "-y")

    assert result.returncode != 0
    assert "no .env" in result.stderr
    assert not (root / ".env").exists()
    assert " up -d" not in docker_log.read_text()


def test_bash_keeps_example_db_password_when_volume_exists(tmp_path):
    root, env, _ = _bash_deploy_fixture(tmp_path)
    _mark_volume_present(root)
    shutil.copy2(REPO_ROOT / ".env.example", root / ".env")

    result = _run_bash(root, env, "-y")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _env_values(root / ".env")["POSTGRES_PASSWORD"] == "change-this-db-password"


@pytest.mark.parametrize("option", ["--host", "--port", "--tag", "--admin-email", "--allowed-hosts"])
def test_bash_option_without_value_fails_before_side_effects(tmp_path, option):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)

    result = _run_bash(root, env, option)

    assert result.returncode != 0
    assert f"Missing value for {option}" in result.stderr
    assert not docker_log.exists()
    assert not (root / ".env").exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--port", "70000"), "Invalid --port"),
        (("--admin-email", "not-an-email"), "Invalid --admin-email"),
        (("--admin-email", "a@b.c\nENV=dev"), "Invalid --admin-email"),
        (("--allowed-hosts", "evil;rm"), "Invalid --allowed-hosts"),
    ],
)
def test_bash_rejects_unsafe_values_before_side_effects(tmp_path, args, message):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)

    result = _run_bash(root, env, *args, "-y")

    assert result.returncode != 0
    assert message in result.stderr
    assert not docker_log.exists()
    assert not (root / ".env").exists()


def test_bash_writes_admin_and_allowed_hosts_on_first_run(tmp_path):
    root, env, _ = _bash_deploy_fixture(tmp_path)

    result = _run_bash(root, env, "--admin-email", "a@example.com,b@example.com", "--allowed-hosts", "192.168.1.5, uh.lan", "-y")

    assert result.returncode == 0, result.stdout + result.stderr
    values = _env_values(root / ".env")
    assert values["ADMIN_EMAILS"] == "a@example.com,b@example.com"
    assert values["ALLOWED_HOSTS"] == "192.168.1.5,uh.lan"


def test_bash_production_env_with_plain_http_origin_is_rejected(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    (root / ".env").write_text(
        f"POSTGRES_PASSWORD=dbpass\nSECRET_KEY={'s' * 64}\nCREDENTIAL_ENCRYPTION_KEY={VALID_FERNET}\n"
        'CORS_ORIGINS=["http://203.0.113.10:8080"]\nENV=production\n',
        encoding="utf-8",
    )

    result = _run_bash(root, env, "-y")

    assert result.returncode != 0
    assert "ENV=production requires https://" in result.stderr
    assert " up -d" not in docker_log.read_text()


def test_bash_failed_start_prints_logs_and_keeps_env(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    docker = root / "bin" / "docker"
    docker.write_text(
        docker.read_text(encoding="utf-8").replace(
            'if [[ "$1" == "compose" ]]; then\n  exit 0',
            'if [[ "$1" == "compose" && " $* " == *" up "* ]]; then\n  exit 1\nfi\nif [[ "$1" == "compose" ]]; then\n  exit 0',
            1,
        ),
        encoding="utf-8",
    )

    result = _run_bash(root, env, "-y")

    assert result.returncode != 0
    assert "The stack did not start" in result.stderr
    assert " logs --tail=80 app postgres" in docker_log.read_text()
    assert (root / ".env").exists()


def test_bash_and_powershell_bind_modes_match_and_tls_proxy_stays_loopback():
    bash = BASH_DEPLOY.read_text(encoding="utf-8")
    powershell = POWERSHELL_DEPLOY.read_text(encoding="utf-8")

    assert 'HTTP_BIND_HOST="127.0.0.1"' in bash
    assert 'if [[ -n "$HOST_IP" && -z "$DOMAIN" ]]; then' in bash
    assert 'HTTP_BIND_HOST="0.0.0.0"' in bash
    assert 'HTTP_BIND_HOST="$HTTP_BIND_HOST" HTTP_PORT=' in bash
    assert "proxy_pass http://127.0.0.1:${HTTP_PORT};" in bash

    assert re.search(
        r'\$HttpBindHost = if \(\$HostIp -and -not \$Domain\) \{ "0\.0\.0\.0" \} ' r'else \{ "127\.0\.0\.1" \}',
        powershell,
    )
    assert "HTTP_BIND_HOST=$HttpBindHost" in powershell
    assert "$env:HTTP_BIND_HOST = $HttpBindHost" in powershell


POWERSHELL_CONTAINER_IMAGE = "mcr.microsoft.com/powershell:7.4-alpine-3.20"
DOCKER_EXECUTABLE = shutil.which("docker")


def _powershell_runtime() -> str | None:
    if shutil.which("pwsh") is not None:
        return "host"
    if DOCKER_EXECUTABLE is None:
        return None
    probe = subprocess.run(
        [DOCKER_EXECUTABLE, "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    return "container" if probe.returncode == 0 else None


POWERSHELL_RUNTIME = _powershell_runtime()


def _powershell_domain_fixture(
    tmp_path: Path, script_source: str, request: pytest.FixtureRequest
) -> tuple[Path, dict[str, str], Path]:
    if POWERSHELL_RUNTIME == "container":
        container_root = Path(tempfile.mkdtemp(prefix=".pytest-powershell-", dir=REPO_ROOT))
        request.addfinalizer(lambda: shutil.rmtree(container_root, ignore_errors=True))
        root = container_root / "powershell-domain"
    else:
        root = tmp_path / "powershell-domain"
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "deploy_server.ps1").write_text(script_source, encoding="utf-8")
    shutil.copy2(COMPOSE_FILE, root / COMPOSE_FILE.name)
    shutil.copytree(REPO_ROOT / "database", root / "database")

    bin_dir = root / "bin"
    bin_dir.mkdir()
    docker_log = root / "docker.log"
    _write_executable(
        bin_dir / "docker",
        """
        #!/bin/sh
        printf '%s\\n' "$*" >> "docker.log"
        case "$1:$2" in
          info:) exit 0 ;;
          compose:version|compose:*) exit 0 ;;
          *) exit 1 ;;
        esac
        """,
    )

    wrapper = root / "run-test.ps1"
    wrapper.write_text(
        textwrap.dedent(
            """
            param(
              [AllowEmptyString()][string]$Domain
            )
            $ErrorActionPreference = 'Stop'
            function Invoke-WebRequest {
              param(
                [Parameter(Position=0)][string]$Uri,
                [switch]$UseBasicParsing,
                [int]$TimeoutSec
              )
              [pscustomobject]@{ StatusCode = 200 }
            }
            function Start-Sleep { param([int]$Seconds) }
            & (Join-Path $PSScriptRoot 'scripts/deploy_server.ps1') -Yes -Domain $Domain
            $childSucceeded = $?
            $childExitCode = $LASTEXITCODE
            if ($childExitCode -is [int] -and $childExitCode -ne 0) {
              exit $childExitCode
            }
            if (-not $childSucceeded) {
              exit 1
            }
            """
        ).lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return wrapper, env, docker_log


def _powershell_command(wrapper: Path, domain: str) -> list[str]:
    if POWERSHELL_RUNTIME == "host":
        return ["pwsh", "-NoProfile", "-File", str(wrapper), "-Domain", domain]
    return [
        DOCKER_EXECUTABLE or "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{wrapper.parent}:/workspace",
        "-w",
        "/workspace",
        "-e",
        "PATH=/workspace/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        POWERSHELL_CONTAINER_IMAGE,
        "/usr/bin/pwsh",
        "-NoProfile",
        "-File",
        "/workspace/run-test.ps1",
        "-Domain",
        domain,
    ]


POWERSHELL_VALID_DOMAINS = [
    "example.com",
    "sub.example.com",
    "xn--fiqs8s.com",
    "a" * 63 + ".example.com",
    ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61]),
]

POWERSHELL_INVALID_DOMAINS = [
    "",
    "example",
    "../../nginx/nginx",
    "https://example.com",
    "example.com/path",
    "example.com:443",
    "example..com",
    "-example.com",
    "example-.com",
    "a" * 64 + ".example.com",
    ".".join(["a" * 63] * 4),
    "example_com",
    "éxample.com",
    "example\t.com",
    "example\n.com",
    "example\r.com",
    "example.com\n",
    "example.com\r\n",
    'example".com',
    "example'.com",
]


def test_powershell_domain_validation_is_strict_and_precedes_side_effects():
    source = POWERSHELL_DEPLOY.read_text(encoding="utf-8")
    validation = source.index("function Validate-Domain")
    invocation = source.index("Validate-Domain $Domain")

    assert invocation > validation
    assert invocation < source.index("Set-Location $RepoRoot")
    assert invocation < source.index("Get-Command docker")
    assert invocation < source.index('Set-Content -Path ".env"')
    assert "[Regex]::IsMatch" in source
    assert r"\A" in source
    assert r"\z" in source
    assert "Length -gt 253" in source
    assert "Length -gt 63" in source
    assert '$PSBoundParameters.ContainsKey("Domain")' in source
    assert "expected an ASCII FQDN (for example example.com)." in source


@pytest.mark.skipif(POWERSHELL_RUNTIME is None, reason="neither pwsh nor a working Docker daemon is available")
@pytest.mark.parametrize("domain", POWERSHELL_VALID_DOMAINS)
def test_powershell_deploy_accepts_ascii_fqdn_matrix(tmp_path, request, domain):
    source = POWERSHELL_DEPLOY.read_text(encoding="utf-8")
    wrapper, env, docker_log = _powershell_domain_fixture(tmp_path, source, request)

    result = subprocess.run(
        _powershell_command(wrapper, domain),
        cwd=wrapper.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert f'CORS_ORIGINS=["https://{domain}"]' in (wrapper.parent / ".env").read_text(encoding="ascii")
    assert docker_log.exists()


@pytest.mark.skipif(POWERSHELL_RUNTIME is None, reason="neither pwsh nor a working Docker daemon is available")
@pytest.mark.parametrize("domain", POWERSHELL_INVALID_DOMAINS)
def test_powershell_deploy_rejects_invalid_domain_before_side_effects(tmp_path, request, domain):
    source = POWERSHELL_DEPLOY.read_text(encoding="utf-8")
    wrapper, env, docker_log = _powershell_domain_fixture(tmp_path, source, request)

    result = subprocess.run(
        _powershell_command(wrapper, domain),
        cwd=wrapper.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0, result.stdout
    assert result.stdout.strip() == "[x] Invalid --domain: expected an ASCII FQDN (for example example.com)."
    assert not docker_log.exists()
    assert not (wrapper.parent / ".env").exists()


@pytest.mark.parametrize(
    ("extra_env", "app_arg", "web_arg"),
    [
        ({}, None, "--build-arg NPM_REGISTRY=https://registry.npmmirror.com "),
        (
            {"BUILD_PIP_INDEX_URL": "https://pypi.org/simple", "BUILD_NPM_REGISTRY": ""},
            "--build-arg PIP_INDEX_URL=https://pypi.org/simple ",
            "--build-arg NPM_REGISTRY= ",
        ),
    ],
)
def test_bash_build_mode_honours_package_mirror_overrides(tmp_path, extra_env, app_arg, web_arg):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    _write_executable(
        root / "bin" / "docker",
        f"""
        #!/usr/bin/env bash
        printf '%s\\n' "$*" >> "{docker_log}"
        if [[ "$1" == "--version" ]]; then
          echo "Docker version 29.4.1, build test"
        elif [[ "$1" == "compose" && "$2" == "version" ]]; then
          echo "Docker Compose version v2.32.0"
        elif [[ "$1" == "volume" ]]; then
          exit 1
        fi
        exit 0
        """,
    )
    env.update(extra_env)

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--build", "-y", "--no-tls"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = docker_log.read_text().splitlines()
    app_build = next(line for line in lines if line.startswith("build -f Dockerfile.server"))
    web_build = next(line for line in lines if line.startswith("build -f Dockerfile.web"))
    if app_arg is None:
        assert "--build-arg" not in app_build
    else:
        assert app_arg in app_build
    assert web_arg in web_build
