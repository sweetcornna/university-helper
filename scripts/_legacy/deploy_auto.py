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

import os
import secrets
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


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


def require_settings() -> None:
    missing = []
    if not SERVER_IP:
        missing.append("EASY_LEARNING_SERVER_IP")
    if not SERVER_PASSWORD:
        missing.append("EASY_LEARNING_SERVER_PASSWORD")
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")


def run(command: str) -> None:
    print(f"$ {command}")
    subprocess.run(command, shell=True, check=True)


def build_sshpass_prefix() -> str:
    password = shlex.quote(SERVER_PASSWORD)
    return f"sshpass -p {password}"


def target() -> str:
    return f"{SERVER_USER}@{SERVER_IP}"


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
    handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    with handle:
        handle.write(content)
    return handle.name


def main() -> None:
    require_settings()

    sshpass = build_sshpass_prefix()
    remote = target()
    remote_dir = shlex.quote(REMOTE_DIR)
    env_file = write_env_file()

    try:
        run(f"{sshpass} ssh -o StrictHostKeyChecking=no {remote} 'mkdir -p {remote_dir}'")
        run(
            f"{sshpass} rsync -avz "
            "--exclude 'node_modules' "
            "--exclude '.git' "
            "--exclude 'dist' "
            "--exclude '__pycache__' "
            "--exclude '.pytest_cache' "
            "--exclude '%TEMP%' "
            f"{shlex.quote(str(LOCAL_DIR))}/ {remote}:{remote_dir}/"
        )
        run(f"{sshpass} scp -o StrictHostKeyChecking=no {shlex.quote(env_file)} {remote}:{remote_dir}/.env")

        remote_cmd = (
            f"cd {remote_dir} && "
            "compose_cmd=$(command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo 'docker compose') && "
            f"$compose_cmd -f {shlex.quote(COMPOSE_FILE)} down || true && "
            f"$compose_cmd -f {shlex.quote(COMPOSE_FILE)} up -d --build && "
            f"$compose_cmd -f {shlex.quote(COMPOSE_FILE)} ps"
        )
        run(f"{sshpass} ssh -o StrictHostKeyChecking=no {remote} {shlex.quote(remote_cmd)}")
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
