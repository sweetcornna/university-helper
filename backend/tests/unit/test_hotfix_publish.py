"""Regression tests for the hotfix publisher's local-to-remote boundaries."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_SOURCE = Path(__file__).resolve().parents[3] / "scripts" / "hotfix_publish.sh"
DEPLOYMENT_DOCS = Path(__file__).resolve().parents[3] / "docs" / "DEPLOYMENT.md"
DEPLOY_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy.yml"
VALID_HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH84F05NZJtXRPAMA4JxtJtUqhAFKe2+FB8cN71iYmBi hotfix test key"
VALID_KNOWN_HOST = f"test.invalid {VALID_HOST_KEY}\n"


@pytest.fixture
def publisher_fixture(tmp_path):
    workspace = tmp_path / "workspace"
    repo = workspace / "repo"
    script = repo / "scripts" / "hotfix_publish.sh"
    target = repo / "backend" / "app" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('fixture')\n")
    (target.parent / "other.py").write_text("print('other fixture')\n")
    (target.parent / "space name.py").write_text("print('spaces')\n")
    (repo / ".env").write_text("SECRET_KEY=fixture-only\n")
    (repo / "Dockerfile.server").write_text("FROM scratch\n")
    nginx_config = repo / "nginx" / "nginx.conf"
    nginx_config.parent.mkdir(parents=True)
    nginx_config.write_text("events {}\n")
    frontend_dist = repo / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("fixture\n")
    frontend_source = repo / "frontend" / "src" / "App.jsx"
    frontend_source.parent.mkdir(parents=True)
    frontend_source.write_text("export default function App() {}\n")
    script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT_SOURCE, script)

    outside = tmp_path / "secret.txt"
    outside.write_text("do not publish\n")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(VALID_KNOWN_HOST)
    known_hosts.chmod(0o600)
    escape = target.parent / "escape.py"
    escape.symlink_to(outside)
    for unsafe_name in ("quote'name.py", "bad\nname.py", "$(touch_marker).py"):
        (target.parent / unsafe_name).write_text("must not publish\n")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    call_log = tmp_path / "network-calls.log"
    call_marker = tmp_path / "network-called"
    fake_transport = """#!/usr/bin/env bash
printf '%s\\n' "$0" >> "$CALL_LOG"
printf '%s\\n' "$@" >> "$CALL_LOG"
: > "$CALL_MARKER"
if [[ "${FAIL_TRANSPORT:-}" == "$(basename "$0")" ]]; then
  exit 42
fi
if [[ -n "${FAIL_REMOTE_SUBSTRING:-}" && "$*" == *"$FAIL_REMOTE_SUBSTRING"* ]]; then
  exit 42
fi
if [[ "$*" == *"mktemp"* ]]; then
  template="$(printf '%s\\n' "$*" | sed -n "s/.*mktemp '\\(.*\\)XXXXXX'.*/\\1/p")"
  [[ -n "$template" ]] || exit 43
  counter_file="${CALL_LOG}.mktemp-counter"
  if [[ -f "$counter_file" ]]; then
    counter="$(<"$counter_file")"
  else
    counter=0
  fi
  counter=$((counter + 1))
  printf '%s\\n' "$counter" > "$counter_file"
  output="${template}${counter}"
  printf 'mktemp-output=%s\\n' "$output" >> "$CALL_LOG"
  if [[ "$template" == *"hotfix-backup."* ]]; then
    printf 'existing|%s\\n' "$output"
  else
    printf '%s\\n' "$output"
  fi
  exit 0
fi
if [[ "$*" == *"{{.Id}}|{{.Image}}"* ]]; then
  printf '%s|%s\\n' "${FAKE_OLD_CONTAINER_ID}" "${FAKE_OLD_IMAGE_ID}"
  exit 0
fi
if [[ "$*" == *"{{.Image}}|{{.Id}}"* ]]; then
  printf '%s|%s\\n' "${FAKE_ROLLBACK_IMAGE_ID}" "${FAKE_ROLLBACK_CONTAINER_ID}"
  exit 0
fi
if [[ "$*" == *"{{.State.Health.Status}}"* ]]; then
  [[ "${FAIL_HEALTH_INSPECT:-}" != "1" ]] || exit 42
  printf '%s\\n' "${FAKE_HEALTH_STATUS:-healthy}"
  exit 0
fi
if [[ "$*" == *"docker image inspect --format '{{.Id}}'"* ]]; then
  [[ "${FAIL_COMPOSE_IMAGE_INSPECT:-}" != "1" ]] || exit 42
  printf '%s\\n' "${FAKE_COMPOSE_IMAGE_INSPECT_ID:-$FAKE_NEW_IMAGE_ID}"
  exit 0
fi
if [[ "$*" == *"{{.Image}}"* ]]; then
  printf '%s\\n' "${FAKE_NEW_IMAGE_ID}"
  exit 0
fi
if [[ "$*" == *"{{.Id}}"* ]]; then
  printf '%s\\n' "${FAKE_NEW_CONTAINER_ID}"
  exit 0
fi
if [[ "$*" == *" images -q app"* ]]; then
  printf '%s\\n' "${FAKE_COMPOSE_IMAGE_ID}"
  exit 0
fi
if [[ "$*" == *"hotfix-image-ref"* ]]; then
  printf '%s\\n' "${FAKE_IMAGE_REF}"
  exit 0
fi
exit 0
"""
    for command in ("ssh", "scp", "rsync"):
        transport = fake_bin / command
        transport.write_text(fake_transport)
        transport.chmod(0o755)

    sshpass = fake_bin / "sshpass"
    sshpass.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "-e" ]]; then
  shift
fi
exec "$@"
"""
    )
    sshpass.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CALL_LOG": str(call_log),
            "CALL_MARKER": str(call_marker),
            "SERVER_IP": "test.invalid",
            "SERVER_USER": "tester",
            "EASY_LEARNING_REMOTE_DIR": "/opt/university-helper",
            "SSH_KNOWN_HOSTS_FILE": str(known_hosts),
            "FAKE_OLD_CONTAINER_ID": "1111111111111111111111111111111111111111111111111111111111111111",
            "FAKE_NEW_CONTAINER_ID": "2222222222222222222222222222222222222222222222222222222222222222",
            "FAKE_OLD_IMAGE_ID": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "FAKE_NEW_IMAGE_ID": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "FAKE_COMPOSE_IMAGE_ID": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "FAKE_ROLLBACK_CONTAINER_ID": "3333333333333333333333333333333333333333333333333333333333333333",
            "FAKE_ROLLBACK_IMAGE_ID": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "FAKE_IMAGE_REF": "university-helper-app:latest",
        }
    )
    for failure_variable in (
        "FAIL_TRANSPORT",
        "FAIL_REMOTE_SUBSTRING",
        "FAIL_HEALTH_INSPECT",
        "FAIL_COMPOSE_IMAGE_INSPECT",
    ):
        env.pop(failure_variable, None)
    return {
        "repo": repo,
        "script": script,
        "outside": outside,
        "fake_bin": fake_bin,
        "known_hosts": known_hosts,
        "env": env,
        "call_log": call_log,
        "call_marker": call_marker,
    }


def run_publisher(fixture, *paths):
    return subprocess.run(
        [str(fixture["script"]), *paths],
        cwd=fixture["repo"],
        env=fixture["env"],
        capture_output=True,
        text=True,
        check=False,
    )


def _scp_target_lines(log):
    return [line for line in log.splitlines() if line.startswith("tester@test.invalid:")]


def test_normal_relative_file_keeps_remote_target_semantics(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert "mkdir -p '/opt/university-helper/backend/app'" in log
    scp_targets = _scp_target_lines(log)
    assert len(scp_targets) == 1
    assert scp_targets[0].startswith("tester@test.invalid:/opt/university-helper/backend/app/main.py.hotfix-stage.")
    assert "'" not in scp_targets[0]
    assert "mv -f '/opt/university-helper/backend/app/main.py.hotfix-stage." in log
    assert "up -d --build --no-deps --force-recreate app" in log
    assert "docker cp" not in log
    assert "docker restart" not in log
    assert publisher_fixture["call_marker"].exists()


def test_dot_prefix_alias_is_canonicalized_before_upload_and_classification(publisher_fixture):
    result = run_publisher(publisher_fixture, "./backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    scp_targets = _scp_target_lines(log)
    assert len(scp_targets) == 1
    assert scp_targets[0].startswith("tester@test.invalid:/opt/university-helper/backend/app/main.py.hotfix-stage.")
    assert "'" not in scp_targets[0]
    assert "mv -f '/opt/university-helper/backend/app/main.py.hotfix-stage." in log
    assert "up -d --build --no-deps --force-recreate app" in log
    assert "docker cp" not in log
    assert "./backend" not in log


def test_space_in_repository_path_is_one_literal_remote_word(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/space name.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert "mkdir -p '/opt/university-helper/backend/app'" in log
    scp_targets = _scp_target_lines(log)
    assert len(scp_targets) == 1
    assert scp_targets[0].startswith(
        "tester@test.invalid:/opt/university-helper/backend/app/space name.py.hotfix-stage."
    )
    assert "'" not in scp_targets[0]
    assert "mv -f '/opt/university-helper/backend/app/space name.py.hotfix-stage." in log
    assert "up -d --build --no-deps --force-recreate app" in log
    assert "docker cp" not in log


def test_non_backend_scp_target_has_no_literal_shell_quotes(publisher_fixture):
    result = run_publisher(publisher_fixture, "nginx/nginx.conf")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    scp_targets = _scp_target_lines(log)
    assert scp_targets == ["tester@test.invalid:/opt/university-helper/nginx/nginx.conf"]
    assert "'" not in scp_targets[0]
    assert "mkdir -p '/opt/university-helper/nginx'" in log


def test_compose_values_are_individually_quoted_in_remote_command(publisher_fixture):
    result = run_publisher(publisher_fixture, "Dockerfile.server")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert (
        "cd '/opt/university-helper' && 'docker-compose' -p 'university-helper' "
        "-f 'docker-compose.server.yml' -f 'docker-compose.newhost.yml' up -d --build --no-deps --force-recreate app"
    ) in log


def test_backend_hotfix_never_writes_to_read_only_app_container():
    script = SCRIPT_SOURCE.read_text(encoding="utf-8")
    compose = (SCRIPT_SOURCE.parents[1] / "docker-compose.server.yml").read_text(encoding="utf-8")

    assert "docker cp" not in script
    assert "docker restart" not in script
    assert "read_only: true" in compose
    assert "up -d --build --no-deps --force-recreate app" in script


def test_backend_hotfix_uploads_then_rebuilds_then_checks_health(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    upload = log.index("tester@test.invalid:/opt/university-helper/backend/app/main.py.hotfix-stage.")
    rebuild = log.index("up -d --build --no-deps --force-recreate app")
    health = log.index("curl -fsS --max-time 5")
    assert upload < rebuild < health
    assert "hotfix-backup." in log
    assert "Hotfix publish complete." in result.stdout


def test_backend_hotfix_revalidates_compose_context_after_upload():
    script = SCRIPT_SOURCE.read_text(encoding="utf-8")

    assert script.count("config --format json") >= 2
    assert "services.app.build.context" in script
    assert "os.path.commonpath" in script
    assert "os.path.isfile(dockerfile_path)" in script
    assert 'validate_remote_build_context "after upload"' in script


def test_multiple_backend_files_use_unique_staging_and_one_rebuild(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py", "backend/app/other.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    mktemp_outputs = [line.split("=", 1)[1] for line in log.splitlines() if line.startswith("mktemp-output=")]
    assert len(mktemp_outputs) == 4
    assert len(set(mktemp_outputs)) == len(mktemp_outputs)
    assert log.count("up -d --build --no-deps --force-recreate app") == 1
    assert log.count("hotfix-stage.") >= 4


def test_backend_hotfix_fails_closed_when_remote_topology_has_no_build_context(publisher_fixture):
    publisher_fixture["env"]["FAIL_REMOTE_SUBSTRING"] = "config --format json) && printf"

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "build-context validation failed" in result.stderr
    assert "Hotfix publish complete." not in result.stdout
    log = publisher_fixture["call_log"].read_text()
    assert "tester@test.invalid:'/opt/university-helper/backend/app/main.py.hotfix-stage." not in log


@pytest.mark.parametrize(
    ("failure_variable", "failure_value", "forbidden_log_fragment"),
    [
        ("FAIL_TRANSPORT", "scp", "up -d --build --no-deps --force-recreate app"),
        ("FAIL_REMOTE_SUBSTRING", "up -d --build --no-deps --force-recreate app", "curl -fsS --max-time 5"),
        ("FAIL_REMOTE_SUBSTRING", "curl -fsS --max-time 5", "Hotfix publish complete."),
    ],
)
def test_backend_upload_rebuild_health_failures_never_claim_success(
    publisher_fixture, failure_variable, failure_value, forbidden_log_fragment
):
    publisher_fixture["env"][failure_variable] = failure_value

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "Hotfix publish complete." not in result.stdout
    log = publisher_fixture["call_log"].read_text()
    assert forbidden_log_fragment not in (result.stdout + result.stderr + log)
    assert "Attempting backend hotfix rollback" in result.stderr
    assert "cp -p -- '/opt/university-helper/backend/app/main.py.hotfix-backup." in log
    assert (
        "docker tag 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' 'university-helper-app:latest'"
        in log
    )
    assert "up -d --no-build --force-recreate --no-deps app" in log
    assert "{{.State.Health.Status}}" in log
    assert "rollback completed and app health is healthy" in result.stderr


def test_backend_hotfix_requires_a_new_container_identity_and_rolls_back(publisher_fixture):
    publisher_fixture["env"]["FAKE_NEW_CONTAINER_ID"] = publisher_fixture["env"]["FAKE_OLD_CONTAINER_ID"]

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "identity is unchanged" in result.stderr
    assert "up -d --no-build --force-recreate --no-deps app" in publisher_fixture["call_log"].read_text()
    assert "Hotfix publish complete." not in result.stdout


def test_backend_hotfix_requires_a_new_image_identity_and_rolls_back(publisher_fixture):
    publisher_fixture["env"]["FAKE_NEW_IMAGE_ID"] = publisher_fixture["env"]["FAKE_OLD_IMAGE_ID"]

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "image identity is unchanged" in result.stderr
    assert "up -d --no-build --force-recreate --no-deps app" in publisher_fixture["call_log"].read_text()
    assert "Hotfix publish complete." not in result.stdout


@pytest.mark.parametrize(
    "invalid_image_id",
    ["", "not-a-digest", "sha256:abcd", f"sha256:{'g' * 64}"],
)
def test_backend_hotfix_rejects_empty_or_malformed_new_image_and_rolls_back(publisher_fixture, invalid_image_id):
    publisher_fixture["env"]["FAKE_NEW_IMAGE_ID"] = invalid_image_id

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "not a full sha256 digest" in result.stderr
    assert "rollback completed" in result.stderr
    assert "Hotfix publish complete." not in result.stdout


def test_backend_hotfix_rejects_compose_image_mismatch_and_rolls_back(publisher_fixture):
    publisher_fixture["env"]["FAKE_COMPOSE_IMAGE_ID"] = (
        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "does not match the Compose app image" in result.stderr
    assert "rollback completed" in result.stderr
    assert "Hotfix publish complete." not in result.stdout


@pytest.mark.parametrize("short_id_length", [12, 64])
def test_backend_hotfix_normalizes_bare_compose_image_id_before_comparison(publisher_fixture, short_id_length):
    short_id = "b" * short_id_length
    publisher_fixture["env"]["FAKE_COMPOSE_IMAGE_ID"] = short_id

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert f"docker image inspect --format '{{{{.Id}}}}' '{short_id}'" in log
    assert "Hotfix publish complete." in result.stdout


@pytest.mark.parametrize(
    ("compose_image_id", "inspect_failure", "normalized_image_id"),
    [
        ("", "0", None),
        ("not-a-digest", "0", None),
        ("a" * 12, "1", None),
        ("a" * 12, "0", "sha256:" + "c" * 64),
    ],
)
def test_backend_hotfix_rejects_compose_image_normalization_failures_and_rolls_back(
    publisher_fixture, compose_image_id, inspect_failure, normalized_image_id
):
    publisher_fixture["env"]["FAKE_COMPOSE_IMAGE_ID"] = compose_image_id
    publisher_fixture["env"]["FAIL_COMPOSE_IMAGE_INSPECT"] = inspect_failure
    if normalized_image_id is not None:
        publisher_fixture["env"]["FAKE_COMPOSE_IMAGE_INSPECT_ID"] = normalized_image_id

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "Attempting backend hotfix rollback" in result.stderr
    assert "rollback completed" in result.stderr
    assert "Hotfix publish complete." not in result.stdout


def test_backend_hotfix_accepts_matching_new_container_and_compose_image(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert publisher_fixture["env"]["FAKE_NEW_IMAGE_ID"] in result.stdout
    log = publisher_fixture["call_log"].read_text()
    assert "docker inspect --format '{{.Image}}'" in log
    assert "docker image inspect --format '{{.Id}}'" not in log
    assert "images -q app" in log
    assert "up -d --no-build --force-recreate --no-deps app" not in log


def test_backend_rollback_verifies_the_restored_old_image_identity(publisher_fixture):
    publisher_fixture["env"]["FAKE_COMPOSE_IMAGE_ID"] = (
        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "{{.Image}}|{{.Id}}" in publisher_fixture["call_log"].read_text()
    assert f"app image {publisher_fixture['env']['FAKE_OLD_IMAGE_ID']} is restored" in result.stderr


def test_backend_rollback_fails_closed_on_wrong_restored_image_identity(publisher_fixture):
    publisher_fixture["env"]["FAKE_COMPOSE_IMAGE_ID"] = (
        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )
    publisher_fixture["env"]["FAKE_ROLLBACK_IMAGE_ID"] = publisher_fixture["env"]["FAKE_NEW_IMAGE_ID"]

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "FATAL: backend hotfix rollback failed" in result.stderr
    assert "rollback completed" not in result.stderr
    assert "Hotfix publish complete." not in result.stdout


def test_frontend_rsync_quotes_remote_path_and_rsh_words(publisher_fixture):
    result = run_publisher(publisher_fixture, "--frontend")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert "tester@test.invalid:/opt/university-helper/frontend/dist/" in log
    assert (
        f"'ssh' '-o' 'StrictHostKeyChecking=yes' '-o' 'UserKnownHostsFile={publisher_fixture['known_hosts']}'"
    ) in log


def test_password_auth_uses_the_same_pinned_host_key_policy(publisher_fixture):
    publisher_fixture["env"]["EASY_LEARNING_SERVER_PASSWORD"] = "fixture-password"

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert "StrictHostKeyChecking=yes" in log
    assert f"UserKnownHostsFile={publisher_fixture['known_hosts']}" in log
    assert "PreferredAuthentications=password" in log
    assert "accept-new" not in log


def test_key_auth_uses_the_same_pinned_host_key_policy(publisher_fixture):
    key = publisher_fixture["repo"] / "fixture-deploy-key"
    key.write_text("not a real key; transport is stubbed\n")
    key.chmod(0o600)
    publisher_fixture["env"]["SSH_KEY"] = str(key)

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert "StrictHostKeyChecking=yes" in log
    assert f"UserKnownHostsFile={publisher_fixture['known_hosts']}" in log
    assert "\n-i\n" in log
    assert f"\n{key}\n" in log
    assert "accept-new" not in log


@pytest.mark.parametrize("known_hosts_case", ["missing", "empty", "unmatched", "malformed"])
def test_invalid_known_hosts_fails_closed_before_any_transport(publisher_fixture, known_hosts_case):
    known_hosts = publisher_fixture["known_hosts"]
    if known_hosts_case == "missing":
        known_hosts.unlink()
    elif known_hosts_case == "empty":
        known_hosts.write_text("")
    elif known_hosts_case == "unmatched":
        known_hosts.write_text(VALID_KNOWN_HOST.replace("test.invalid", "other.invalid"))
    else:
        known_hosts.write_text("test.invalid ssh-ed25519 NOT_BASE64\n")

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "SSH_KNOWN_HOSTS_FILE" in result.stderr
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_known_hosts_accepts_tab_separators_and_crlf(publisher_fixture):
    publisher_fixture["known_hosts"].write_bytes(
        f"# trusted fixture\r\n\r\ntest.invalid\t{VALID_HOST_KEY}\r\n".encode()
    )

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert publisher_fixture["call_marker"].exists()


def install_ssh_keygen_lookup_passthrough(publisher_fixture):
    """Make host lookup preserve valid separators unsupported by older macOS ssh-keygen."""
    real_ssh_keygen = shutil.which("ssh-keygen")
    assert real_ssh_keygen is not None
    publisher_fixture["env"]["REAL_SSH_KEYGEN"] = real_ssh_keygen
    shim = publisher_fixture["fake_bin"] / "ssh-keygen"
    shim.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "-F" ]]; then
  printf '# Host %s found\n' "${2:-}"
  exec /bin/cat "${4:-}"
fi
exec "$REAL_SSH_KEYGEN" "$@"
"""
    )
    shim.chmod(0o755)


def test_revoked_only_with_tab_separators_and_crlf_fails_before_transport(publisher_fixture):
    install_ssh_keygen_lookup_passthrough(publisher_fixture)
    publisher_fixture["known_hosts"].write_bytes(f"@revoked\ttest.invalid\t{VALID_HOST_KEY}\r\n".encode())

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "matching entry is revoked" in result.stderr
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_mixed_revoked_and_valid_matches_are_accepted(publisher_fixture):
    install_ssh_keygen_lookup_passthrough(publisher_fixture)
    publisher_fixture["known_hosts"].write_bytes(
        (f"@revoked\ttest.invalid\t{VALID_HOST_KEY}\r\ntest.invalid\t{VALID_HOST_KEY}\r\n").encode()
    )

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert publisher_fixture["call_marker"].exists()


def test_known_hosts_accepts_hashed_host_entry(publisher_fixture):
    known_hosts = publisher_fixture["known_hosts"]
    hash_result = subprocess.run(
        ["ssh-keygen", "-H", "-f", str(known_hosts)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert hash_result.returncode == 0, hash_result.stderr
    assert known_hosts.read_text().startswith("|1|")

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert publisher_fixture["call_marker"].exists()


def test_known_hosts_accepts_bracketed_default_port_entry(publisher_fixture):
    publisher_fixture["known_hosts"].write_text(f"[test.invalid]:22 {VALID_HOST_KEY}\n")

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert publisher_fixture["call_marker"].exists()


def test_known_hosts_accepts_bracketed_ipv6_default_port_entry(publisher_fixture):
    publisher_fixture["env"]["SERVER_IP"] = "2001:db8::1"
    publisher_fixture["known_hosts"].write_text(f"[2001:db8::1]:22 {VALID_HOST_KEY}\n")

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert publisher_fixture["call_marker"].exists()


@pytest.mark.parametrize(
    "invalid_entry",
    [
        "test.invalid\n",
        "@unsupported test.invalid ssh-ed25519 AAAA\n",
        "test.invalid not-a-key AAAA\n",
    ],
)
def test_unparseable_known_hosts_entry_fails_closed_before_transport(publisher_fixture, invalid_entry):
    publisher_fixture["known_hosts"].write_text(invalid_entry)

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert "SSH_KNOWN_HOSTS_FILE" in result.stderr
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_missing_known_hosts_is_allowed_only_for_dry_run(publisher_fixture):
    publisher_fixture["env"].pop("SSH_KNOWN_HOSTS_FILE")
    publisher_fixture["env"].pop("EASY_LEARNING_SSH_KNOWN_HOSTS_FILE", None)

    result = run_publisher(publisher_fixture, "--dry-run", "./backend/app/main.py")

    assert result.returncode == 0, result.stderr
    assert "Dry run" in result.stdout
    assert "backend/app/main.py" in result.stdout
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_frontend_dry_run_never_requires_known_hosts_or_rsync(publisher_fixture):
    publisher_fixture["env"].pop("SSH_KNOWN_HOSTS_FILE")
    publisher_fixture["env"].pop("EASY_LEARNING_SSH_KNOWN_HOSTS_FILE", None)

    result = run_publisher(publisher_fixture, "--dry-run", "--frontend")

    assert result.returncode == 0, result.stderr
    assert "would sync frontend/dist/" in result.stdout
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_frontend_source_is_rejected_before_network_calls(publisher_fixture):
    result = run_publisher(publisher_fixture, "frontend/src/App.jsx")

    assert result.returncode != 0
    assert "Frontend source paths are not accepted in per-file mode" in result.stderr
    assert "cd frontend && npm ci && npm run build" in result.stderr
    assert "./scripts/hotfix_publish.sh --frontend" in result.stderr
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_mixed_backend_and_frontend_sources_are_rejected_before_network_calls(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py", "frontend/src/App.jsx")

    assert result.returncode != 0
    assert "Frontend source paths are not accepted in per-file mode" in result.stderr
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_hotfix_docs_require_built_dist_frontend_mode():
    document = DEPLOYMENT_DOCS.read_text(encoding="utf-8")
    section = document.split("## Deploying a Hotfix (small code change)", 1)[1].split(
        "## First-Time Server Bootstrap", 1
    )[0]
    normalized_section = " ".join(section.split())

    assert "frontend/src/" not in section
    assert "cd frontend && npm ci && npm run build" in section
    assert "./scripts/hotfix_publish.sh --frontend" in section
    assert "atomic rename" not in normalized_section.lower()
    assert "does not make the overall multi-file and container update atomic" in normalized_section

    chinese_section = document.split("## 推送热修（小改动）", 1)[1].split("## 全新服务器初始化", 1)[0]
    assert "frontend/src/" not in chinese_section
    assert "cd frontend && npm ci && npm run build" in chinese_section
    assert "./scripts/hotfix_publish.sh --frontend" in chinese_section
    assert "backend/app/api/v1/course.py" in chinese_section
    assert "原子重命名" not in chinese_section
    assert "不承诺整个多文件与容器更新是原子的" in chinese_section


def test_deploy_workflow_passes_trusted_known_hosts_without_tofu():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    publish_step = workflow.split("      - name: Publish to production", 1)[1]

    assert "SERVER_SSH_KNOWN_HOSTS: ${{ secrets.SERVER_SSH_KNOWN_HOSTS }}" in publish_step
    assert "SSH_KNOWN_HOSTS_FILE=" in publish_step
    assert "mktemp" in publish_step
    assert "chmod 600" in publish_step
    assert "trap" in publish_step
    assert "StrictHostKeyChecking=yes" in SCRIPT_SOURCE.read_text(encoding="utf-8")
    assert "accept-new" not in SCRIPT_SOURCE.read_text(encoding="utf-8")
    assert "ssh-keyscan" not in workflow


@pytest.mark.parametrize(
    ("variable", "malicious_value"),
    [
        ("SERVER_IP", "test.invalid bad"),
        ("SERVER_USER", "tester'bad"),
        ("EASY_LEARNING_REMOTE_DIR", "/opt/university-helper;id"),
        ("EASY_LEARNING_COMPOSE_BIN", "$(touch /tmp/hotfix-pwned)"),
        ("EASY_LEARNING_COMPOSE_FILES", "docker-compose.yml $(id)"),
        ("EASY_LEARNING_COMPOSE_PROJECT", "project\nnext"),
        ("EASY_LEARNING_APP_CONTAINER", "app;id"),
        ("EASY_LEARNING_WEB_CONTAINER", "web$(id)"),
        ("EASY_LEARNING_APP_BACKEND_DIR", "/srv/backend bad"),
        ("EASY_LEARNING_HEALTH_URL", "http://127.0.0.1:8000/health'$(id)"),
        ("SSH_KEY", "/tmp/key'bad"),
    ],
)
def test_unsafe_environment_config_is_rejected_before_network_calls(publisher_fixture, variable, malicious_value):
    publisher_fixture["env"][variable] = malicious_value

    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode != 0
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_password_metacharacters_never_enter_rsync_shell_command(publisher_fixture):
    injection_marker = publisher_fixture["repo"] / "password-injection-ran"
    password = f"space ' ;$(touch {injection_marker})\nsecond-line"
    publisher_fixture["env"]["EASY_LEARNING_SERVER_PASSWORD"] = password

    result = run_publisher(publisher_fixture, "--frontend")

    assert result.returncode == 0, result.stderr
    assert not injection_marker.exists()
    assert password not in publisher_fixture["call_log"].read_text()


@pytest.mark.parametrize(
    "malicious_path",
    [
        "",
        ".",
        "../../secret.txt",
        "backend/../../secret.txt",
        "backend/../.env",
        "backend/../frontend/src/App.jsx",
        "backend/app/../app/main.py",
        "backend/app/escape.py",
        "backend/app/quote'name.py",
        "backend/app/bad\nname.py",
        "backend/app/$(touch_marker).py",
    ],
)
def test_malicious_path_is_rejected_before_network_calls(publisher_fixture, malicious_path):
    result = run_publisher(publisher_fixture, malicious_path)

    assert result.returncode != 0
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_absolute_path_is_rejected_before_network_calls(publisher_fixture):
    path = str(publisher_fixture["repo"] / "backend" / "app" / "main.py")

    result = run_publisher(publisher_fixture, path)

    assert result.returncode != 0
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_late_invalid_path_does_not_publish_an_earlier_valid_path(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py", "../../secret.txt")

    assert result.returncode != 0
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()
