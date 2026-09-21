#!/usr/bin/env python3
"""
Upload the current project and deploy it with docker-compose.yml.

Required environment variables:
  EASY_LEARNING_SERVER_IP
  EASY_LEARNING_SERVER_PASSWORD

Optional environment variables:
  EASY_LEARNING_SERVER_USER=root
  EASY_LEARNING_PROJECT_NAME=easy_learning
  EASY_LEARNING_REMOTE_DIR=/opt/easy_learning
  EASY_LEARNING_COMPOSE_FILE=docker-compose.yml
  EASY_LEARNING_POSTGRES_PASSWORD=change-this-db-password
  EASY_LEARNING_SECRET_KEY=<generated automatically>
  EASY_LEARNING_SHUAKE_COMPAT_SECRET=
  EASY_LEARNING_CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
"""

from __future__ import annotations

import ipaddress
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

LOCAL_DIR = Path(__file__).resolve().parent
SERVER_IP = os.getenv("EASY_LEARNING_SERVER_IP", "")
SERVER_USER = os.getenv("EASY_LEARNING_SERVER_USER", "root") or "root"
SERVER_PASSWORD = os.getenv("EASY_LEARNING_SERVER_PASSWORD", "").strip()
PROJECT_NAME = (
    os.getenv("EASY_LEARNING_PROJECT_NAME", "easy_learning") or "easy_learning"
)
REMOTE_DIR = (
    os.getenv("EASY_LEARNING_REMOTE_DIR", f"/opt/{PROJECT_NAME}")
    or f"/opt/{PROJECT_NAME}"
)
COMPOSE_FILE = (
    os.getenv("EASY_LEARNING_COMPOSE_FILE", "docker-compose.yml")
    or "docker-compose.yml"
)
POSTGRES_PASSWORD = os.getenv(
    "EASY_LEARNING_POSTGRES_PASSWORD", "change-this-db-password"
).strip()
SECRET_KEY = os.getenv("EASY_LEARNING_SECRET_KEY", "").strip() or secrets.token_hex(32)
SHUAKE_COMPAT_SECRET = os.getenv("EASY_LEARNING_SHUAKE_COMPAT_SECRET", "").strip()
CORS_ORIGINS = os.getenv(
    "EASY_LEARNING_CORS_ORIGINS",
    '["http://localhost:3000","http://localhost:5173"]',
).strip()


SERVER_USER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")
HOSTNAME_LABEL_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
REMOTE_PATH_PATTERN = re.compile(r"[A-Za-z0-9_./~:@%+=,-]+\Z")
# ``accept-new`` keeps first-time unattended deploys working, but rejects a key
# change for hosts already present in the user's known_hosts file.
SSH_HOST_KEY_OPTION = "StrictHostKeyChecking=accept-new"


def require_settings() -> None:
    missing = []
    if not SERVER_IP:
        missing.append("EASY_LEARNING_SERVER_IP")
    if not SERVER_PASSWORD:
        missing.append("EASY_LEARNING_SERVER_PASSWORD")
    if missing:
        raise SystemExit(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    _validate_settings()


def run(command: Sequence[str]) -> None:
    """Run one local command without giving a shell any opportunity to parse it."""
    command_args = list(command)
    display_args = command_args.copy()
    try:
        password_index = display_args.index("-p")
    except ValueError:
        pass
    else:
        if password_index + 1 < len(display_args):
            display_args[password_index + 1] = "***"
    print(f"$ {shlex.join(display_args)}")
    subprocess.run(command_args, shell=False, check=True)


def build_sshpass_prefix() -> list[str]:
    return ["sshpass", "-p", SERVER_PASSWORD]


def _reject_invalid_setting(name: str, description: str) -> None:
    raise SystemExit(f"Invalid {name}: {description}")


def _validate_server_user(value: str) -> None:
    if not isinstance(value, str) or not SERVER_USER_PATTERN.fullmatch(value):
        _reject_invalid_setting(
            "EASY_LEARNING_SERVER_USER", "expected a simple username"
        )


def _validate_server_host(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 253:
        _reject_invalid_setting(
            "EASY_LEARNING_SERVER_IP", "expected an IPv4, IPv6, or DNS hostname"
        )

    try:
        ipaddress.ip_address(value)
        return
    except ValueError:
        pass

    hostname = value.removesuffix(".")
    if (
        not hostname
        or len(hostname) > 253
        or not all(
            HOSTNAME_LABEL_PATTERN.fullmatch(label) for label in hostname.split(".")
        )
    ):
        _reject_invalid_setting(
            "EASY_LEARNING_SERVER_IP", "expected an IPv4, IPv6, or DNS hostname"
        )


def _validate_remote_path(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or not REMOTE_PATH_PATTERN.fullmatch(value)
    ):
        _reject_invalid_setting(name, "expected a shell-safe remote path")


def _validate_settings() -> None:
    _validate_server_user(SERVER_USER)
    _validate_server_host(SERVER_IP)
    _validate_remote_path("EASY_LEARNING_REMOTE_DIR", REMOTE_DIR)
    _validate_remote_path("EASY_LEARNING_COMPOSE_FILE", COMPOSE_FILE)


def target() -> str:
    _validate_server_user(SERVER_USER)
    _validate_server_host(SERVER_IP)
    return f"{SERVER_USER}@{SERVER_IP}"


def remote_path_target(path: str) -> str:
    """Build an rsync/scp target, bracketing IPv6 where their syntax needs it."""
    _validate_server_user(SERVER_USER)
    _validate_server_host(SERVER_IP)
    if not isinstance(path, str) or not path:
        raise ValueError("remote path must be a non-empty string")

    host = SERVER_IP
    try:
        is_ipv6 = ipaddress.ip_address(SERVER_IP).version == 6
    except ValueError:
        is_ipv6 = False
    if is_ipv6:
        host = f"[{host}]"
    return f"{SERVER_USER}@{host}:{path}"


def write_env_file() -> str:
    content = "\n".join(
        [
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            f"SECRET_KEY={SECRET_KEY}",
            f"SHUAKE_COMPAT_SECRET={SHUAKE_COMPAT_SECRET}",
            f"CORS_ORIGINS={CORS_ORIGINS}",
            "",
        ]
    )
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write(content)
    return handle.name


def main() -> None:
    require_settings()

    sshpass = build_sshpass_prefix()
    remote = target()
    remote_dir = shlex.quote(REMOTE_DIR)
    env_file = write_env_file()

    try:
        run(
            [
                *sshpass,
                "ssh",
                "-o",
                SSH_HOST_KEY_OPTION,
                remote,
                f"mkdir -p {remote_dir}",
            ]
        )
        run(
            [
                *sshpass,
                "rsync",
                "-avz",
                "--exclude",
                "node_modules",
                "--exclude",
                ".git",
                "--exclude",
                "dist",
                "--exclude",
                "__pycache__",
                "--exclude",
                ".pytest_cache",
                "--exclude",
                "%TEMP%",
                f"{LOCAL_DIR}/",
                remote_path_target(f"{REMOTE_DIR}/"),
            ]
        )
        run(
            [
                *sshpass,
                "scp",
                "-o",
                SSH_HOST_KEY_OPTION,
                env_file,
                remote_path_target(f"{REMOTE_DIR}/.env"),
            ]
        )

        remote_cmd = (
            f"cd {remote_dir} && "
            "compose_cmd=$(command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo 'docker compose') && "
            f"$compose_cmd -f {shlex.quote(COMPOSE_FILE)} down || true && "
            f"$compose_cmd -f {shlex.quote(COMPOSE_FILE)} up -d --build && "
            f"$compose_cmd -f {shlex.quote(COMPOSE_FILE)} ps"
        )
        run(
            [
                *sshpass,
                "ssh",
                "-o",
                SSH_HOST_KEY_OPTION,
                remote,
                remote_cmd,
            ]
        )
    finally:
        try:
            os.remove(env_file)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
