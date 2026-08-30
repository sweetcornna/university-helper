"""Guardrails for source deployments that serve the SPA from host nginx."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DEPLOYMENT_BLOCKS = (
    (REPO_ROOT / "README.md", "### Manual (build from source)", "## Security"),
    (REPO_ROOT / "README.zh-CN.md", "### 手动部署（从源码构建）", "## 测试"),
    (REPO_ROOT / "docs" / "DEPLOYMENT.md", "## First-Time Server Bootstrap", "## Operations"),
    (REPO_ROOT / "docs" / "DEPLOYMENT.md", "## 全新服务器初始化", "## 运维"),
)
SERVER_BOOTSTRAP_BLOCKS = (
    (REPO_ROOT / "docs" / "DEPLOYMENT.md", "## First-Time Server Bootstrap", "## Operations"),
    (REPO_ROOT / "docs" / "DEPLOYMENT.md", "## 全新服务器初始化", "## 运维"),
)
SITE_DEPLOYMENT_SECTION = REPO_ROOT / "site" / "wiki.html"
BUILD_COMMAND = "cd frontend && npm ci && npm run build"
NODE_20 = re.compile(r"\bNode(?:\.js)?\s+20\b", re.IGNORECASE)


def _between(document: str, start_marker: str, end_marker: str) -> str:
    start = document.index(start_marker)
    end = document.index(end_marker, start)
    return document[start:end]


def _source_deployment_blocks() -> list[tuple[Path, str]]:
    blocks = []
    for path, start_marker, end_marker in SOURCE_DEPLOYMENT_BLOCKS:
        document = path.read_text(encoding="utf-8")
        blocks.append((path, _between(document, start_marker, end_marker)))

    document = SITE_DEPLOYMENT_SECTION.read_text(encoding="utf-8")
    section_start = document.index('<section class="wiki-sec" id="deploy">')
    section = document[section_start : document.index("</section>", section_start)]
    # The topology paragraph mentions nginx before the commands. Start at the
    # source command block so the ordering assertion covers deploy actions.
    code_start = section.index('<div class="wiki-code">')
    blocks.append((SITE_DEPLOYMENT_SECTION, section[code_start:]))
    return blocks


def test_source_deployments_build_frontend_before_host_nginx_or_health_check():
    for path, raw_block in _source_deployment_blocks():
        block = unescape(raw_block)
        label = str(path.relative_to(REPO_ROOT))
        build_pos = block.find(BUILD_COMMAND)
        assert build_pos >= 0, f"{label} must build the SPA with npm ci before Compose"
        assert NODE_20.search(block), f"{label} must require Node.js 20 for source builds"

        return_to_root_pos = block.find("cd ..", build_pos + len(BUILD_COMMAND))
        assert return_to_root_pos >= 0, f"{label} must return to the repository root after building"

        tail = block[build_pos + len(BUILD_COMMAND) :]
        dist_pos = tail.find("frontend/dist")
        assert dist_pos >= 0, f"{label} must document the generated frontend/dist"
        nginx_or_health = re.search(r"nginx|health|验证", tail, re.IGNORECASE)
        assert nginx_or_health, f"{label} must document nginx serving or health verification"
        assert dist_pos < nginx_or_health.start(), f"{label} must generate dist before nginx/verification"


def test_server_bootstrap_keeps_clone_and_sync_in_the_repository_root():
    for path, start_marker, end_marker in SERVER_BOOTSTRAP_BLOCKS:
        document = path.read_text(encoding="utf-8")
        block = _between(document, start_marker, end_marker)
        label = f"{path.relative_to(REPO_ROOT)} ({start_marker})"

        assert re.search(r"git clone\s+<repo>\s+\.", block), f"{label} must clone into the current directory"
        assert re.search(r"rsync\s+<source>/\s+\./", block), f"{label} must sync into the current directory"
        assert "/opt/university-helper/.env" in block, f"{label} must retain the repository-root env path"
