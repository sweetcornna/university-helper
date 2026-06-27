# Releasing

A release is cut by pushing a `v*` git tag. The `release` workflow
(`.github/workflows/release.yml`) fans out from that one tag into:

- **create-release** — a *draft* GitHub Release (so every build leg attaches to one release).
- **images** — multi-arch `app` + `web` server images → GHCR (`:<version>` and `:latest`).
- **desktop** — Windows / macOS (arm64 + Intel) / Linux installers + updater artifacts (Tauri).
- **publish** — flips the draft to published only when images **and every** desktop leg succeed.

The git tag is the single source of truth for the version; `scripts/set_version.sh`
stamps it into all five manifests (`frontend/package.json`, `backend/pyproject.toml`,
`backend/app/main.py`, `frontend/src-tauri/{tauri.conf.json,Cargo.toml}`).

## Cutting a release

```bash
# 1. Stamp + commit the version BEFORE tagging (the images job builds the tagged tree;
#    the desktop legs also re-stamp their checkout, so this is belt-and-suspenders).
bash scripts/set_version.sh 1.4.0
git commit -am "chore: v1.4.0"
git tag v1.4.0
git push --follow-tags
# 2. Watch it: gh run watch  → create-release → images + desktop → publish (all green)
# 3. Verify: gh release view v1.4.0  → installers (.msi/.dmg/.AppImage) + latest.json attached
```

macOS caveat: the `x86_64-apple-darwin` desktop leg runs on a native Intel `macos-13`
runner because PyInstaller cannot cross-compile the sidecar; `aarch64-apple-darwin` runs
on the Apple-Silicon `macos-latest`.

## Updater signing keypair (free, one-time)

The Tauri auto-updater needs a signing keypair (separate from OS code-signing; it is free).
Without it, installers still build but carry no `.sig`/`latest.json` and won't auto-update.

```bash
cd frontend
npm install                                   # ensures @tauri-apps/cli is available
npm run tauri signer generate -- -w ~/.tauri/uh-updater.key
#   (equivalent: npx @tauri-apps/cli@latest signer generate -w ~/.tauri/uh-updater.key)
```

It prompts for a password (recommended) and writes:
- `~/.tauri/uh-updater.key` — **private** key (NEVER commit; becomes a GitHub secret).
- `~/.tauri/uh-updater.key.pub` — public key (committed inside `tauri.conf.json`).

Store the secrets and wire the public key:

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/uh-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD            # prompts; do not echo into history
gh secret list | grep TAURI_SIGNING
```

A default keypair is **already wired**: `frontend/src-tauri/tauri.conf.json`
`plugins.updater.pubkey` holds a committed public key (no-password key generated at setup),
so signed releases auto-update out of the box **once you add the matching private key** as the
`TAURI_SIGNING_PRIVATE_KEY` secret (above). To use your own key instead, regenerate as above and
paste the new `.pub` content into `plugins.updater.pubkey`; keep `endpoints` at
`https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json`.
For production, prefer a **password-protected** key (set `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`).

Checklist:
- [ ] `chmod 600 ~/.tauri/uh-updater.key`; the key + `.pub` live **outside** the repo (never staged).
- [ ] `gh secret list` shows `TAURI_SIGNING_PRIVATE_KEY` and `_PASSWORD`.
- [ ] `tauri.conf.json` `plugins.updater.pubkey` equals the `.pub` content.
- [ ] A signed desktop leg emits `*.sig` + `latest.json`; an unsigned leg still produces installers.

## GHCR: make server images anonymously pullable (one-time)

So the one-click `deploy_server.sh` (and the §11 deploy fix-forward) can `docker pull`
without a login.

```bash
# (a) Allow Actions to write packages (UI: Settings → Actions → General → Workflow permissions → Read and write)
gh api -X PUT /repos/sweetcornna/university-helper/actions/permissions/workflow \
  -f default_workflow_permissions=write -F can_approve_pull_request_reviews=false

# (b) (Re)publish images for a tag
gh workflow run release.yml -f tag=v1.3.0 && gh run watch

# (c) Make both container packages PUBLIC
gh api -X PATCH /user/packages/container/university-helper-app -f visibility=public
gh api -X PATCH /user/packages/container/university-helper-web -f visibility=public
#   (UI fallback: Profile → Packages → <pkg> → Package settings → Change visibility → Public)

# (d) Verify anonymous pull
docker logout ghcr.io
docker pull ghcr.io/sweetcornna/university-helper-web:latest
docker pull ghcr.io/sweetcornna/university-helper-app:latest
```

Once both pull anonymously, the reported `Invalid host header` / `dependency app failed
to start` deploy bug is fixed at the distribution level: a clean box running
`bash scripts/deploy_server.sh --tag v1.3.0` pulls the current fixed images (which always
seed `localhost`/`127.0.0.1` as TrustedHost patterns, `backend/app/main.py`), so the
healthcheck no longer 400s.

## Code-signing status (free-first)

- **Linux** — no signing needed (`.AppImage`/`.deb`).
- **Windows** — pursuing the free [SignPath Foundation](https://signpath.org/) OSS program; until
  approved, builds are unsigned (SmartScreen "More info → Run anyway").
- **macOS** — ad-hoc signed (Gatekeeper "right-click → Open"); an optional Apple Developer ID
  ($99/yr) for notarization is planned. The CI signing steps are gated on secrets, so adding them
  later needs no workflow change.
