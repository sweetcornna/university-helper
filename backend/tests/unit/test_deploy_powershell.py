"""deploy_server.ps1: exit codes, .env reconciliation and volume guard."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy_server.ps1"
PWSH = shutil.which("pwsh")
VALID_FERNET = "A" * 43 + "="

needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh unavailable")


def test_every_docker_step_checks_its_exit_code():
    source = SCRIPT.read_text(encoding="utf-8")
    for call in ("Compose pull", "Compose up -d", "docker build -f Dockerfile.server", "docker build -f Dockerfile.web"):
        index = source.index(call)
        following = source[index : index + 400]
        assert "$LASTEXITCODE -ne 0" in following, call


def test_validation_happens_before_any_side_effect():
    source = SCRIPT.read_text(encoding="utf-8")
    first_side_effect = min(
        source.index("Set-Location $RepoRoot"),
        source.index("Get-Command docker"),
        source.index('Set-Content -Path ".env"'),
        source.index("Invoke-SourceBootstrap }"),
    )
    for guard in ("Invalid -HostIp", "Invalid -Port", "Invalid -AdminEmail", "Invalid -AllowedHosts"):
        assert source.index(guard) < first_side_effect, guard


def _fixture(tmp_path: Path, *, volume_exists: bool = False, with_repo: bool = True) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / "ps"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "deploy_server.ps1")
    if with_repo:
        shutil.copy2(REPO_ROOT / "docker-compose.release.yml", root / "docker-compose.release.yml")
        shutil.copytree(REPO_ROOT / "database", root / "database")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    log = root / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "$*" >> "{log}"
            case "$1:$2" in
              volume:inspect) exit {0 if volume_exists else 1} ;;
              info:*|compose:*) exit 0 ;;
            esac
            exit 1
            """
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    wrapper = root / "run.ps1"
    wrapper.write_text(
        textwrap.dedent(
            """
            $ErrorActionPreference = 'Stop'
            function Invoke-WebRequest {
              param([Parameter(Position=0)][string]$Uri, [switch]$UseBasicParsing, [int]$TimeoutSec, [string]$OutFile)
              if ($OutFile) {
                Add-Content -LiteralPath $env:T_WEBLOG -Value $Uri
                Copy-Item -LiteralPath $env:T_ZIP -Destination $OutFile
                return
              }
              [pscustomobject]@{ StatusCode = 200; Content = '{"status":"ok","schema":"ok"}' }
            }
            function Start-Sleep { param([int]$Seconds) }
            $params = @{ Yes = $true }
            if ($env:T_DOMAIN) { $params.Domain = $env:T_DOMAIN }
            if ($env:T_ADMIN) { $params.AdminEmail = $env:T_ADMIN }
            if ($env:T_TAG) { $params.Tag = $env:T_TAG }
            & (Join-Path $PSScriptRoot 'scripts/deploy_server.ps1') @params
            if ($LASTEXITCODE -is [int] -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            if (-not $?) { exit 1 }
            """
        ).lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return root, env, log


def _run(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PWSH or "pwsh", "-NoProfile", "-File", str(root / "run.ps1")],
        cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
    )


@needs_pwsh
def test_powershell_redeploy_keeps_secrets_and_applies_flags(tmp_path):
    root, env, _ = _fixture(tmp_path)
    secret = "s" * 64
    (root / ".env").write_text(
        f"POSTGRES_PASSWORD=dbpass\nSECRET_KEY={secret}\nCREDENTIAL_ENCRYPTION_KEY={VALID_FERNET}\n"
        'CORS_ORIGINS=["http://localhost:8080"]\nENV=dev\nHTTP_BIND_HOST=127.0.0.1\nHTTP_PORT=8080\n',
        encoding="utf-8",
    )
    env["T_DOMAIN"] = "example.test"
    env["T_ADMIN"] = "ops@example.test"

    result = _run(root, env)

    assert result.returncode == 0, result.stdout
    text = (root / ".env").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=dbpass" in text
    assert f"SECRET_KEY={secret}" in text
    assert 'CORS_ORIGINS=["https://example.test"]' in text
    assert "ENV=production" in text
    assert "ADMIN_EMAILS=ops@example.test" in text
    assert "Database ready for registration" in result.stdout


@needs_pwsh
def test_powershell_fills_example_placeholders(tmp_path):
    root, env, _ = _fixture(tmp_path)
    shutil.copy2(REPO_ROOT / ".env.example", root / ".env")

    result = _run(root, env)

    assert result.returncode == 0, result.stdout
    text = (root / ".env").read_text(encoding="utf-8")
    assert re.search(r"^CREDENTIAL_ENCRYPTION_KEY=[A-Za-z0-9_-]{43}=$", text, re.M)
    assert "change-this" not in text


@needs_pwsh
def test_powershell_refuses_new_secrets_when_volume_exists(tmp_path):
    root, env, log = _fixture(tmp_path, volume_exists=True)

    result = _run(root, env)

    assert result.returncode != 0
    assert "no .env" in result.stdout
    assert not (root / ".env").exists()
    assert "up -d" not in log.read_text()


@needs_pwsh
def test_powershell_offline_mode_refuses_to_download(tmp_path):
    root, env, log = _fixture(tmp_path, with_repo=False)
    env["UH_DEPLOY_OFFLINE"] = "1"

    result = _run(root, env)

    assert result.returncode != 0
    assert "UH_DEPLOY_OFFLINE=1" in result.stdout
    assert not log.exists()


def _release_zip(tmp_path: Path) -> Path:
    # A fake GitHub source zip whose installer only records how it was started.
    src = tmp_path / "zipsrc" / "university-helper-9.9.9"
    (src / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", src / "docker-compose.release.yml")
    shutil.copytree(REPO_ROOT / "database", src / "database")
    (src / "scripts" / "deploy_server.ps1").write_text(
        'param([string]$Tag, [switch]$Yes)\n'
        'Set-Content -LiteralPath $env:T_CHILD_LOG -Value "child Tag=$Tag Yes=$Yes boot=$env:UH_BOOTSTRAPPED"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    archive = shutil.make_archive(str(tmp_path / "source"), "zip", root_dir=src.parent)
    return Path(archive)


@needs_pwsh
@pytest.mark.parametrize(("installed", "refreshed"), [("v9.9.0", True), ("v9.9.9", False)])
def test_powershell_update_refreshes_downloaded_source_for_a_new_tag(tmp_path, installed, refreshed):
    root, env, log = _fixture(tmp_path)
    (root / ".uh-source-tag").write_text(f"{installed}\n", encoding="ascii")
    (root / ".env").write_text("POSTGRES_PASSWORD=keepme\n", encoding="utf-8")
    weblog, child_log = tmp_path / "web.log", tmp_path / "child.log"
    env.update(
        T_TAG="9.9.9", T_ZIP=str(_release_zip(tmp_path)), T_WEBLOG=str(weblog), T_CHILD_LOG=str(child_log)
    )

    result = _run(root, env)

    if refreshed:
        assert result.returncode == 0, result.stdout
        assert "from v9.9.0 to v9.9.9" in result.stdout
        assert weblog.read_text().strip().endswith("/archive/refs/tags/v9.9.9.zip")
        assert (root / ".uh-source-tag").read_text().strip() == "v9.9.9"
        assert child_log.read_text().strip() == "child Tag=9.9.9 Yes=True boot=1"
        assert "POSTGRES_PASSWORD=keepme" in (root / ".env").read_text()
        assert not log.exists()
    else:
        assert not weblog.exists()
        assert not child_log.exists()
        assert (root / "scripts" / "deploy_server.ps1").read_text() == SCRIPT.read_text()
