#!/usr/bin/env python3
"""Build and check the desktop auto-update manifest (latest.json).

Each desktop build job in release.yml uploads its installers and ``.sig`` files
to the draft release. This script runs once after all of them have finished,
so latest.json has exactly one writer.

``assemble``
    Download every updater bundle and its signature from the draft release,
    verify each one with minisign against the public key in tauri.conf.json,
    write latest.json and upload it.

``verify``
    After the release is published, fetch
    ``<base>/<repo>/releases/latest/download/latest.json`` and check the
    version and that every download URL answers.

Only the standard library is used; ``gh`` and ``minisign`` must be on PATH.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TAURI_CONF = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
ASSET_PREFIX = "xuedao"
MAX_NOTES_CHARS = 4000


@dataclass(frozen=True)
class Target:
    key: str
    suffix: str
    required: bool


# Asset names come from tauri-action's assetNamePattern
# "xuedao_[version]_[platform]_[arch][setup][ext]".
TARGETS = (
    Target("darwin-aarch64-app", "darwin_aarch64.app.tar.gz", True),
    Target("darwin-x86_64-app", "darwin_x64.app.tar.gz", True),
    Target("windows-x86_64-nsis", "windows_x64-setup.exe", True),
    Target("windows-x86_64-msi", "windows_x64.msi", False),
    Target("linux-x86_64-appimage", "linux_amd64.AppImage", True),
    Target("linux-x86_64-deb", "linux_amd64.deb", False),
)

# The updater looks up "<os>-<arch>-<installer>" first and then "<os>-<arch>".
# There is deliberately no plain "linux-x86_64": a .deb install without its own
# entry would fall back to it and try to install an AppImage as a .deb. Without
# the fallback it just finds no update. On Windows either installer can
# replace an existing install, so NSIS is a safe fallback for MSI installs.
ALIASES = {
    "darwin-aarch64": "darwin-aarch64-app",
    "darwin-x86_64": "darwin-x86_64-app",
    "windows-x86_64": "windows-x86_64-nsis",
}

REQUIRED_KEYS = frozenset({t.key for t in TARGETS if t.required} | set(ALIASES))


class ManifestError(RuntimeError):
    pass


def asset_name(version: str, target: Target) -> str:
    return f"{ASSET_PREFIX}_{version}_{target.suffix}"


def download_url(repository: str, tag: str, name: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{name}"


def release_notes(version: str, changelog: Path = CHANGELOG) -> str:
    """Return the CHANGELOG section for ``version`` without its heading."""
    if not changelog.is_file():
        return f"学道 {version}"
    lines: list[str] = []
    grabbing = False
    for line in changelog.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"## [{version}]"):
            grabbing = True
            continue
        if grabbing and line.startswith("## ["):
            break
        if grabbing:
            lines.append(line)
    notes = "\n".join(lines).strip()
    return (notes or f"学道 {version}")[:MAX_NOTES_CHARS]


def public_key_text(conf_path: Path = TAURI_CONF) -> str:
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    encoded = conf["plugins"]["updater"]["pubkey"]
    return base64.b64decode(encoded).decode("utf-8")


def _run(args: list[str], *, stdout=None) -> subprocess.CompletedProcess:
    result = subprocess.run(args, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise ManifestError(f"{' '.join(args[:3])} failed ({result.returncode}): {stderr}")
    return result


def list_assets(repository: str, release_id: str) -> dict[str, int]:
    result = _run(["gh", "api", f"repos/{repository}/releases/{release_id}/assets?per_page=100"])
    return {item["name"]: int(item["id"]) for item in json.loads(result.stdout)}


def download_asset(repository: str, asset_id: int, dest: Path) -> None:
    with dest.open("wb") as handle:
        _run(
            [
                "gh",
                "api",
                "-H",
                "Accept: application/octet-stream",
                f"repos/{repository}/releases/assets/{asset_id}",
            ],
            stdout=handle,
        )


def verify_signature(pubkey_file: Path, artifact: Path, signature_b64: str, workdir: Path) -> None:
    try:
        decoded = base64.b64decode(signature_b64, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError(f"{artifact.name}.sig is not a base64 minisign signature") from exc
    sig_file = workdir / f"{artifact.name}.minisig"
    sig_file.write_text(decoded, encoding="utf-8")
    result = subprocess.run(
        ["minisign", "-V", "-q", "-p", str(pubkey_file), "-m", str(artifact), "-x", str(sig_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ManifestError(
            f"{artifact.name}: signature does not match the updater public key in tauri.conf.json "
            f"(is TAURI_SIGNING_PRIVATE_KEY the key for that pubkey?) {result.stderr.strip()}"
        )


def build_platforms(
    repository: str,
    tag: str,
    version: str,
    assets: dict[str, int],
    workdir: Path,
    pubkey_file: Path,
) -> dict[str, dict[str, str]]:
    present: list[Target] = []
    problems: list[str] = []
    for target in TARGETS:
        name = asset_name(version, target)
        sig_name = f"{name}.sig"
        has_bundle, has_sig = name in assets, sig_name in assets
        if has_bundle and has_sig:
            present.append(target)
            continue
        missing = ", ".join(n for n, ok in ((name, has_bundle), (sig_name, has_sig)) if not ok)
        if target.required:
            problems.append(f"{target.key}: missing {missing}")
        else:
            print(f"--  {target.key:<24} skipped (missing {missing})")
    # Check names before downloading hundreds of megabytes.
    if problems:
        available = ", ".join(sorted(assets)) or "none"
        raise ManifestError(
            "updater bundles are incomplete:\n  " + "\n  ".join(problems) + f"\nassets on the release: {available}"
        )

    platforms: dict[str, dict[str, str]] = {}
    for target in present:
        name = asset_name(version, target)
        sig_name = f"{name}.sig"
        artifact = workdir / name
        sig_path = workdir / sig_name
        download_asset(repository, assets[name], artifact)
        download_asset(repository, assets[sig_name], sig_path)
        signature = sig_path.read_text(encoding="utf-8").strip()
        verify_signature(pubkey_file, artifact, signature, workdir)
        platforms[target.key] = {"signature": signature, "url": download_url(repository, tag, name)}
        print(f"ok  {target.key:<24} {name}")
    for alias, key in ALIASES.items():
        platforms[alias] = platforms[key]
    return platforms


def build_manifest(version: str, notes: str, platforms: dict[str, dict[str, str]]) -> dict:
    return {
        "version": version,
        "notes": notes,
        "pub_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": dict(sorted(platforms.items())),
    }


def assemble(args: argparse.Namespace) -> None:
    assets = list_assets(args.repository, args.release_id)
    with tempfile.TemporaryDirectory(prefix="uh-updater-") as tmp:
        workdir = Path(tmp)
        pubkey_file = workdir / "updater.pub"
        pubkey_file.write_text(public_key_text(args.tauri_conf), encoding="utf-8")
        platforms = build_platforms(args.repository, args.tag, args.version, assets, workdir, pubkey_file)
        manifest = build_manifest(args.version, release_notes(args.version, args.changelog), platforms)
        output = workdir / "latest.json"
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _run(["gh", "release", "upload", args.tag, str(output), "--clobber", "--repo", args.repository])
    if "latest.json" not in list_assets(args.repository, args.release_id):
        raise ManifestError("latest.json was uploaded but is not listed on the release")
    print(f"latest.json uploaded with {len(manifest['platforms'])} platform entries")


def _status(url: str, timeout: float) -> int:
    # Ask for one byte so a 100 MB installer is not downloaded just to see it exists.
    request = urllib.request.Request(url, headers={"User-Agent": "university-helper-release", "Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https/test URLs
        return response.status


def check_live_manifest(base_url: str, repository: str, version: str, timeout: float) -> list[str]:
    manifest_url = f"{base_url.rstrip('/')}/{repository}/releases/latest/download/latest.json"
    try:
        request = urllib.request.Request(manifest_url, headers={"User-Agent": "university-helper-release"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            manifest = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return [f"{manifest_url}: {exc}"]
    problems: list[str] = []
    if manifest.get("version") != version:
        problems.append(f"latest.json version is {manifest.get('version')!r}, expected {version!r}")
    platforms = manifest.get("platforms") or {}
    for key in sorted(REQUIRED_KEYS - set(platforms)):
        problems.append(f"latest.json has no {key} entry")
    for url in sorted({entry.get("url", "") for entry in platforms.values()}):
        try:
            status = _status(url, timeout)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            problems.append(f"{url}: {exc}")
            continue
        if status not in (200, 206):
            problems.append(f"{url}: HTTP {status}")
    for key, entry in platforms.items():
        if not entry.get("signature"):
            problems.append(f"{key} has an empty signature")
    return problems


def verify(args: argparse.Namespace) -> None:
    problems: list[str] = []
    for attempt in range(1, args.attempts + 1):
        problems = check_live_manifest(args.base_url, args.repository, args.version, args.timeout)
        if not problems:
            print(f"latest.json for {args.version} is live and every download URL answers")
            return
        if attempt < args.attempts:
            print(f"attempt {attempt}/{args.attempts} failed, retrying in {args.delay:g}s")
            time.sleep(args.delay)
    raise ManifestError("published updater manifest is not usable:\n  " + "\n  ".join(problems))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("assemble", help="build, verify and upload latest.json to the draft release")
    build.add_argument("--repository", required=True)
    build.add_argument("--release-id", required=True)
    build.add_argument("--tag", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--tauri-conf", type=Path, default=TAURI_CONF)
    build.add_argument("--changelog", type=Path, default=CHANGELOG)
    build.set_defaults(func=assemble)

    check = sub.add_parser("verify", help="check the published latest.json")
    check.add_argument("--repository", required=True)
    check.add_argument("--version", required=True)
    check.add_argument("--base-url", default="https://github.com")
    check.add_argument("--attempts", type=int, default=6)
    check.add_argument("--delay", type=float, default=10.0)
    check.add_argument("--timeout", type=float, default=30.0)
    check.set_defaults(func=verify)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        args.func(args)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
