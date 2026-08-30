"""Static and network checks for the marketing site's external scripts."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import subprocess
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE_DIR = REPO_ROOT / "site"

EXPECTED_EXTERNAL_SRI = {
    "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js": (
        "sha384-g4NTh/Iv5PPU4xPyhEWqPcwtNXOvdaDI8LLnyYfyNZOjKJeYQyjzQ9X5275eBjpt"
    ),
    "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js": (
        "sha384-Z3REaz79l2IaAZqJsSABtTbhjgOUYyV3p90XNnAPCSHg3EMTz1fouunq9WZRtj3d"
    ),
}

SHA384_RE = re.compile(r"^sha384-[A-Za-z0-9+/]{64}$")
PINNED_JSDELIVR_NPM_RE = re.compile(
    r"^https://cdn\.jsdelivr\.net/npm/(?:@[^/]+/)?[^@/?#]+@" r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?/[^?#]+$"
)


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.external_scripts: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return

        attributes = {name.lower(): value for name, value in attrs}
        src = attributes.get("src")
        if src and src.lower().startswith("https://"):
            self.external_scripts.append((src, attributes))


def _external_scripts() -> list[tuple[str, dict[str, str | None]]]:
    scripts: list[tuple[str, dict[str, str | None]]] = []
    site_html = sorted((*SITE_DIR.rglob("*.html"), *SITE_DIR.rglob("*.htm")))
    assert site_html, f"no HTML files found in {SITE_DIR}"
    for html_path in site_html:
        parser = _ScriptParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        parser.close()
        scripts.extend(parser.external_scripts)
    return scripts


def _sri_sha384(content: bytes) -> str:
    digest = hashlib.sha384(content).digest()
    return "sha384-" + base64.b64encode(digest).decode("ascii")


def _download_script(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "gzip",
            "User-Agent": "university-helper-site-sri-test/1",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content_encoding = response.headers.get("Content-Encoding", "").strip().lower()
        encoded_content = response.read()

    if content_encoding == "gzip":
        content = gzip.decompress(encoded_content)
    elif content_encoding in {"", "identity"}:
        content = encoded_content
    else:
        raise AssertionError(f"unsupported CDN Content-Encoding for {url}: {content_encoding}")

    return content, content_encoding or "identity"


def test_site_external_scripts_are_pinned_and_have_sha384_sri():
    scripts = _external_scripts()
    assert scripts, "site HTML must contain the site's external scripts"
    assert {src for src, _ in scripts} == set(EXPECTED_EXTERNAL_SRI)

    for src, attributes in scripts:
        assert PINNED_JSDELIVR_NPM_RE.fullmatch(src), f"external script URL is not pinned: {src}"
        integrity = attributes.get("integrity")
        assert integrity is not None and SHA384_RE.fullmatch(
            integrity
        ), f"external script has invalid SHA-384 SRI: {src}"
        assert attributes.get("crossorigin") == "anonymous", f"external script must set crossorigin=anonymous: {src}"
        assert integrity == EXPECTED_EXTERNAL_SRI[src]


def test_site_external_scripts_match_sri_from_network():
    """Download each active CDN script and verify its browser-visible bytes."""
    for src, attributes in _external_scripts():
        content, content_encoding = _download_script(src)
        actual_sri = _sri_sha384(content)
        assert actual_sri == attributes["integrity"], (
            f"SRI mismatch for {src}: {actual_sri} ({len(content)} decompressed bytes; "
            f"Content-Encoding: {content_encoding})"
        )
        print(f"{src} -> {actual_sri} ({len(content)} bytes; Content-Encoding: {content_encoding})")


def test_site_night_script_handles_missing_scrolltrigger_without_stopping_common_init():
    """Run the browser script in a VM for both CDN loading outcomes."""
    night_script = json.dumps((SITE_DIR / "assets" / "night.js").read_text(encoding="utf-8"))
    node_harness = f"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = {night_script};

function run(withScrollTrigger) {{
  const htmlClasses = new Set();
  const bodyToggles = [];
  const events = [];
  const registered = [];
  const stars = {{
    children: [],
    style: {{}},
    appendChild(child) {{ this.children.push(...child.children); }}
  }};
  const gsap = {{
    registerPlugin(plugin) {{ registered.push(plugin); }},
    set() {{}},
  }};
  const scrollTrigger = {{}};
  const document = {{
    documentElement: {{
      scrollHeight: 1000,
      classList: {{ add(name) {{ htmlClasses.add(name); }} }},
    }},
    body: {{ classList: {{ toggle(name, value) {{ bodyToggles.push([name, value]); }} }} }},
    createDocumentFragment() {{
      return {{ children: [], appendChild(child) {{ this.children.push(child); }} }};
    }},
    createElement() {{
      return {{ className: '', style: {{ setProperty() {{}} }} }};
    }},
    getElementById(id) {{ return id === 'stars' ? stars : null; }},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
  }};
  const window = {{
    innerHeight: 600,
    scrollY: 0,
    gsap,
    matchMedia() {{ return {{ matches: withScrollTrigger }}; }},
    addEventListener(name) {{ events.push(name); }},
  }};
  if (withScrollTrigger) window.ScrollTrigger = scrollTrigger;
  const context = {{ window, document, requestAnimationFrame(callback) {{ callback(); }} }};
  vm.runInNewContext(source, context);
  return {{ bodyToggles, events, htmlClasses, registered, scrollTrigger, stars }};
}}

const fallback = run(false);
assert.equal(fallback.registered.length, 0);
assert.equal(fallback.stars.children.length, 110);
assert.deepEqual(fallback.events.sort(), ['resize', 'scroll']);
assert.equal(fallback.bodyToggles.length, 1);
assert.equal(fallback.htmlClasses.has('js-anim'), false);

const animated = run(true);
assert.deepEqual(animated.registered, [animated.scrollTrigger]);
assert.equal(animated.htmlClasses.has('js-anim'), true);
"""
    result = subprocess.run(
        ["node", "--eval", node_harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr or result.stdout
