"""Tests for scripts/updater_manifest.py with fake gh and minisign binaries."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "updater_manifest.py"
REPOSITORY = "owner/university-helper"
VERSION = "1.4.7"
TAG = "v1.4.7"
KEY_ID = "TESTKEY"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import updater_manifest  # noqa: E402

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path

release = Path(os.environ["FAKE_RELEASE_DIR"])
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
args = sys.argv[1:]
names = sorted(p.name for p in release.iterdir())
if args[:1] == ["api"] and args[-1].endswith("/assets?per_page=100"):
    print(json.dumps([{"id": i, "name": n} for i, n in enumerate(names)]))
elif args[:1] == ["api"] and "/releases/assets/" in args[-1]:
    sys.stdout.buffer.write((release / names[int(args[-1].rsplit("/", 1)[1])]).read_bytes())
elif args[:2] == ["release", "upload"]:
    if os.environ.get("FAKE_GH_UPLOAD_FAILS"):
        print("upload failed", file=sys.stderr)
        sys.exit(1)
    shutil.copy(args[3], release / Path(args[3]).name)
else:
    print("unexpected gh call: " + " ".join(args), file=sys.stderr)
    sys.exit(2)
"""

# Accepts a signature only if it names the public key's id and the file's sha256.
FAKE_MINISIGN = r"""#!/usr/bin/env python3
import hashlib, sys
args = sys.argv[1:]
opt = {args[i]: args[i + 1] for i in range(len(args) - 1) if args[i] in ("-p", "-m", "-x")}
pub = open(opt["-p"], encoding="utf-8").read()
sig = open(opt["-x"], encoding="utf-8").read()
digest = hashlib.sha256(open(opt["-m"], "rb").read()).hexdigest()
key_id = pub.split("public key: ", 1)[1].split()[0]
if f"key={key_id}" in sig and f"sha256={digest}" in sig:
    sys.exit(0)
print("Signature verification failed", file=sys.stderr)
sys.exit(1)
"""


def _executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _signature(payload: bytes, key_id: str = KEY_ID) -> str:
    text = f"untrusted comment: signature\nkey={key_id} sha256={hashlib.sha256(payload).hexdigest()}\n"
    return base64.b64encode(text.encode()).decode()


def _add_bundle(release: Path, name: str, *, signed: bool = True, key_id: str = KEY_ID) -> None:
    payload = f"bundle {name}".encode()
    (release / name).write_bytes(payload)
    if signed:
        (release / f"{name}.sig").write_text(_signature(payload, key_id), encoding="utf-8")


@pytest.fixture
def env(tmp_path: Path) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "gh", FAKE_GH)
    _executable(bin_dir / "minisign", FAKE_MINISIGN)

    release = tmp_path / "release"
    release.mkdir()
    for suffix in (
        "darwin_aarch64.app.tar.gz",
        "darwin_x64.app.tar.gz",
        "windows_x64-setup.exe",
        "windows_x64.msi",
        "linux_amd64.AppImage",
    ):
        _add_bundle(release, f"xuedao_{VERSION}_{suffix}")
    _add_bundle(release, f"xuedao_{VERSION}_linux_amd64.deb", signed=False)
    (release / f"xuedao_{VERSION}_darwin_aarch64.dmg").write_bytes(b"dmg")

    pubkey = base64.b64encode(f"untrusted comment: minisign public key: {KEY_ID}\nRWTEST\n".encode()).decode()
    conf = tmp_path / "tauri.conf.json"
    conf.write_text(json.dumps({"plugins": {"updater": {"pubkey": pubkey}}}), encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n## [{VERSION}] - 2026-09-16\n\n### Fixed\n- 注册不再报 internal error\n\n## [1.4.6]\n- old\n",
        encoding="utf-8",
    )

    variables = os.environ.copy()
    variables.update(
        PATH=f"{bin_dir}{os.pathsep}{variables['PATH']}",
        FAKE_RELEASE_DIR=str(release),
        FAKE_GH_LOG=str(tmp_path / "gh.log"),
    )
    return {"vars": variables, "release": release, "conf": conf, "changelog": changelog, "tmp": tmp_path}


def _assemble(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "assemble",
            "--repository",
            REPOSITORY,
            "--release-id",
            "42",
            "--tag",
            TAG,
            "--version",
            VERSION,
            "--tauri-conf",
            str(env["conf"]),
            "--changelog",
            str(env["changelog"]),
        ],
        env=env["vars"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_assemble_writes_one_manifest_with_installer_keys_and_aliases(env):
    result = _assemble(env)

    assert result.returncode == 0, result.stderr
    manifest = json.loads((env["release"] / "latest.json").read_text(encoding="utf-8"))
    platforms = manifest["platforms"]
    assert manifest["version"] == VERSION
    assert manifest["notes"] == "### Fixed\n- 注册不再报 internal error"
    assert manifest["pub_date"].endswith("Z")
    assert set(platforms) == {
        "darwin-aarch64-app",
        "darwin-x86_64-app",
        "windows-x86_64-nsis",
        "windows-x86_64-msi",
        "linux-x86_64-appimage",
        "darwin-aarch64",
        "darwin-x86_64",
        "windows-x86_64",
    }
    base = f"https://github.com/{REPOSITORY}/releases/download/{TAG}"
    assert platforms["windows-x86_64"] == platforms["windows-x86_64-nsis"]
    assert platforms["windows-x86_64-nsis"]["url"] == f"{base}/xuedao_{VERSION}_windows_x64-setup.exe"
    assert platforms["darwin-x86_64-app"]["url"] == f"{base}/xuedao_{VERSION}_darwin_x64.app.tar.gz"
    assert platforms["linux-x86_64-appimage"]["url"] == f"{base}/xuedao_{VERSION}_linux_amd64.AppImage"
    sig = (env["release"] / f"xuedao_{VERSION}_linux_amd64.AppImage.sig").read_text(encoding="utf-8")
    assert platforms["linux-x86_64-appimage"]["signature"] == sig
    # An unsigned .deb is left out, and so is a bare linux-x86_64 fallback that
    # would hand an AppImage to a .deb install.
    assert "linux-x86_64-deb" not in platforms
    assert "linux-x86_64" not in platforms
    assert "linux-x86_64-deb" in result.stdout


def test_missing_required_bundle_fails_before_downloading_anything(env):
    (env["release"] / f"xuedao_{VERSION}_darwin_x64.app.tar.gz.sig").unlink()

    result = _assemble(env)

    assert result.returncode == 1
    assert f"darwin-x86_64-app: missing xuedao_{VERSION}_darwin_x64.app.tar.gz.sig" in result.stderr
    assert not (env["release"] / "latest.json").exists()
    gh_calls = (env["tmp"] / "gh.log").read_text(encoding="utf-8")
    assert "/releases/assets/" not in gh_calls
    assert "release upload" not in gh_calls


def test_old_non_ascii_asset_names_are_reported_as_missing(env):
    for path in list(env["release"].iterdir()):
        path.rename(path.with_name(path.name.replace("xuedao", "")))

    result = _assemble(env)

    assert result.returncode == 1
    assert "updater bundles are incomplete" in result.stderr
    assert f"_{VERSION}_windows_x64-setup.exe" in result.stderr


def test_signature_from_another_key_is_rejected(env):
    _add_bundle(env["release"], f"xuedao_{VERSION}_windows_x64-setup.exe", key_id="OTHERKEY")

    result = _assemble(env)

    assert result.returncode == 1
    assert "signature does not match the updater public key" in result.stderr
    assert not (env["release"] / "latest.json").exists()


def test_tampered_bundle_is_rejected(env):
    (env["release"] / f"xuedao_{VERSION}_linux_amd64.AppImage").write_bytes(b"tampered")

    result = _assemble(env)

    assert result.returncode == 1
    assert f"xuedao_{VERSION}_linux_amd64.AppImage: signature does not match" in result.stderr


def test_failed_upload_fails_the_job(env):
    env["vars"]["FAKE_GH_UPLOAD_FAILS"] = "1"

    result = _assemble(env)

    assert result.returncode == 1
    assert "gh release upload failed" in result.stderr


def test_real_tauri_public_key_decodes_to_minisign_format():
    text = updater_manifest.public_key_text()

    assert text.startswith("untrusted comment: minisign public key: ")
    assert len(text.splitlines()) == 2


def test_release_notes_fall_back_when_the_version_has_no_section(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0]\n- first\n", encoding="utf-8")

    assert updater_manifest.release_notes("9.9.9", changelog) == "学道 9.9.9"
    assert updater_manifest.release_notes("9.9.9", tmp_path / "missing.md") == "学道 9.9.9"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def site(tmp_path: Path):
    root = tmp_path / "site"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield root, base
    finally:
        server.shutdown()
        server.server_close()


def _publish(root: Path, base: str, *, version: str = VERSION, drop: str = "") -> None:
    latest = root / REPOSITORY / "releases" / "latest" / "download"
    files = root / "files"
    latest.mkdir(parents=True)
    files.mkdir(parents=True)
    platforms = {}
    for key in sorted(updater_manifest.REQUIRED_KEYS):
        name = f"{key}.bin"
        if key != drop:
            (files / name).write_bytes(b"x")
        platforms[key] = {"signature": "c2ln", "url": f"{base}/files/{name}"}
    manifest = {"version": version, "notes": "", "pub_date": "2026-09-16T00:00:00Z", "platforms": platforms}
    (latest / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_verify_accepts_a_complete_live_manifest(site):
    root, base = site
    _publish(root, base)

    assert updater_manifest.check_live_manifest(base, REPOSITORY, VERSION, timeout=5) == []


def test_verify_reports_wrong_version_and_dead_urls(site):
    root, base = site
    _publish(root, base, version="1.4.6", drop="windows-x86_64-nsis")

    problems = updater_manifest.check_live_manifest(base, REPOSITORY, VERSION, timeout=5)

    assert "latest.json version is '1.4.6', expected '1.4.7'" in problems
    assert any("windows-x86_64-nsis.bin" in problem and "404" in problem for problem in problems)


def test_verify_command_retries_then_fails_when_manifest_is_missing(site):
    _, base = site

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--repository",
            REPOSITORY,
            "--version",
            VERSION,
            "--base-url",
            base,
            "--attempts",
            "2",
            "--delay",
            "0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "attempt 1/2 failed" in result.stdout
    assert "published updater manifest is not usable" in result.stderr
