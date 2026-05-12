#!/usr/bin/env python3
"""
Deploy the project with Paramiko.

Required environment variables:
  EASY_LEARNING_SERVER_IP
  EASY_LEARNING_SERVER_PASSWORD
"""

from __future__ import annotations

import os
import posixpath
import secrets
import sys
from pathlib import Path

try:
    import paramiko
except ImportError as exc:
    raise SystemExit("Install paramiko first: pip install paramiko") from exc


LOCAL_DIR = Path(__file__).resolve().parent
SERVER_IP = os.getenv("EASY_LEARNING_SERVER_IP", "").strip()
SERVER_USER = os.getenv("EASY_LEARNING_SERVER_USER", "root").strip() or "root"
SERVER_PASSWORD = os.getenv("EASY_LEARNING_SERVER_PASSWORD", "").strip()
PROJECT_NAME = os.getenv("EASY_LEARNING_PROJECT_NAME", "easy_learning").strip() or "easy_learning"
REMOTE_DIR = os.getenv("EASY_LEARNING_REMOTE_DIR", f"/opt/{PROJECT_NAME}").strip() or f"/opt/{PROJECT_NAME}"
COMPOSE_FILE = os.getenv("EASY_LEARNING_COMPOSE_FILE", "docker-compose.yml").strip() or "docker-compose.yml"
POSTGRES_PASSWORD = os.getenv("EASY_LEARNING_POSTGRES_PASSWORD", "change-this-db-password").strip()
SECRET_KEY = os.getenv("EASY_LEARNING_SECRET_KEY", "").strip() or secrets.token_hex(32)
SHUAKE_COMPAT_SECRET = os.getenv("EASY_LEARNING_SHUAKE_COMPAT_SECRET", "").strip()
CORS_ORIGINS = os.getenv(
    "EASY_LEARNING_CORS_ORIGINS",
    '["http://localhost:3000","http://localhost:5173"]',
).strip()

IGNORE_DIRS = {"node_modules", "__pycache__", ".git", ".pytest_cache", "dist", "%TEMP%"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}


def require_settings() -> None:
    missing = []
    if not SERVER_IP:
        missing.append("EASY_LEARNING_SERVER_IP")
    if not SERVER_PASSWORD:
        missing.append("EASY_LEARNING_SERVER_PASSWORD")
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")


def ensure_remote_dir(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    parts = []
    current = remote_path
    while current not in ("", "/"):
        parts.append(current)
        current = posixpath.dirname(current)
    for path in reversed(parts):
        try:
            sftp.stat(path)
        except OSError:
            sftp.mkdir(path)


def upload_tree(sftp: paramiko.SFTPClient, local_root: Path, remote_root: str) -> None:
    ensure_remote_dir(sftp, remote_root)
    for path in local_root.rglob("*"):
        relative = path.relative_to(local_root)
        if any(part in IGNORE_DIRS for part in relative.parts):
            continue
        if path.suffix in IGNORE_SUFFIXES:
            continue

        remote_path = posixpath.join(remote_root, *relative.parts)
        if path.is_dir():
            ensure_remote_dir(sftp, remote_path)
            continue

        ensure_remote_dir(sftp, posixpath.dirname(remote_path))
        sftp.put(str(path), remote_path)


def run_remote(ssh: paramiko.SSHClient, command: str) -> None:
    print(f"$ {command}")
    stdin, stdout, stderr = ssh.exec_command(command, get_pty=True)
    exit_status = stdout.channel.recv_exit_status()
    sys.stdout.write(stdout.read().decode("utf-8", errors="ignore"))
    sys.stderr.write(stderr.read().decode("utf-8", errors="ignore"))
    if exit_status != 0:
        raise SystemExit(exit_status)


def compose_command() -> str:
    return "$(command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo 'docker compose')"


def write_remote_env(sftp: paramiko.SFTPClient, remote_root: str) -> None:
    env_content = "\n".join(
        [
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            f"SECRET_KEY={SECRET_KEY}",
            f"SHUAKE_COMPAT_SECRET={SHUAKE_COMPAT_SECRET}",
            f"CORS_ORIGINS={CORS_ORIGINS}",
            "",
        ]
    )
    remote_env = posixpath.join(remote_root, ".env")
    with sftp.file(remote_env, "w") as handle:
        handle.write(env_content)


def main() -> None:
    require_settings()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        SERVER_IP,
        username=SERVER_USER,
        password=SERVER_PASSWORD,
        timeout=20,
        look_for_keys=False,
        allow_agent=False,
    )

    try:
        sftp = ssh.open_sftp()
        try:
            upload_tree(sftp, LOCAL_DIR, REMOTE_DIR)
            write_remote_env(sftp, REMOTE_DIR)
        finally:
            sftp.close()

        compose_cmd = compose_command()
        run_remote(ssh, f"cd {REMOTE_DIR} && {compose_cmd} -f {COMPOSE_FILE} down || true")
        run_remote(ssh, f"cd {REMOTE_DIR} && {compose_cmd} -f {COMPOSE_FILE} up -d --build")
        run_remote(ssh, f"cd {REMOTE_DIR} && {compose_cmd} -f {COMPOSE_FILE} ps")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
