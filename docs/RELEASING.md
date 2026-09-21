# Releasing

Pushing a `v*` git tag cuts a release. The `release` workflow
(`.github/workflows/release.yml`) starts from that tag and runs these jobs:

- `create-release` makes a *draft* GitHub Release, so every build job attaches its files to the
  same release. In this repository it also stops the run straight away if the updater signing key
  is missing (see [Updater signing keypair](#updater-signing-keypair-free-one-time)).
- `app-image` and `web-image` build the multi-arch server images independently and push each one
  to its GHCR repository under an immutable `:<image_version>` tag only. The build action reports
  the content digest for the promotion step. These jobs never build or push `:latest`.
- `desktop` builds the Windows, macOS (arm64 and Intel) and Linux installers plus the signed
  updater bundles with Tauri.
- `updater-manifest` runs once after every desktop build and is the only job that writes
  `latest.json`.
- `promote-images` retags each exact image digest as `:latest` in its own GHCR repository once
  every build has passed.
- `publish` turns the draft into a published release after promotion and every desktop build
  have succeeded, then checks the live `latest.json`.

The git tag is the single source of truth for the version. `scripts/set_version.sh`
stamps it into all eight versioned files—six manifests (`frontend/package.json`,
`frontend/package-lock.json`, `backend/pyproject.toml`, `backend/app/main.py`,
`frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml`) plus two lockfiles
(`backend/uv.lock`, `frontend/src-tauri/Cargo.lock`).
The workflow's `tag`, `version` and `release_id` outputs keep their existing contract, and
`create-release` also exports `updater` (`true` when the release is signed). Only the Docker tag is
normalized, as `image_version`: a `+` in version metadata becomes `_` because Docker tags do not
allow `+`.

## Cutting a release

```bash
# 1. Stamp + commit the version on main. Push main and wait for the main-branch
#    CI run to pass before creating any release tag.
bash scripts/set_version.sh 1.4.0
git commit -am "chore: v1.4.0"
MAIN_SHA="$(git rev-parse HEAD)"
git push origin main
gh run list --workflow test.yml --branch main --commit "$MAIN_SHA" --limit 5
gh run watch <main-ci-run-id> --exit-status
# If this push changed frontend/** (or the deploy workflow), also wait for the
# frontend production deploy to finish before tagging.
gh run list --workflow deploy.yml --branch main --commit "$MAIN_SHA" --limit 5
gh run watch <frontend-deploy-run-id> --exit-status

# 2. Create an annotated tag only after the checks/deploy above succeed, then
#    push that tag explicitly; keep the tag push as a separate command.
git tag -a v1.4.0 -m v1.4.0
git push origin v1.4.0

# 3. Watch the tag-triggered release workflow:
gh run list --workflow release.yml --limit 5
gh run watch <release-run-id> --exit-status

# 4. Verify the assets: xuedao_* installers, a .sig next to each updater bundle,
#    latest.json, deploy_server.sh / deploy_server.ps1, docker-compose.release.yml
gh release view v1.4.0 --json assets --jq '.assets[].name'
# The updater endpoint must return the new version and every platform key
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json \
  | jq '.version, (.platforms | keys)'
```

In this path, the explicitly pushed `v1.4.0` tag triggers the `release` workflow. Waiting for
the `main` CI run, and for the frontend production deploy when that workflow runs, keeps the
release build from racing a main-branch validation or frontend deploy that is still in progress.
If the push did not match the deploy workflow's `paths` filter, there is no frontend deploy run to
wait for, but you should still confirm that CI passed before tagging.

### Immutable-first image promotion and publication

The server images follow an all-gates-before-promotion flow:

1. `app-image` and `web-image` each build and push their multi-arch image under the immutable
   `:<image_version>` tag and return the digest produced by `docker/build-push-action`.
2. The `promote-images` job waits for `create-release`, `app-image`, `web-image`, `desktop`, and `updater-manifest`.
   It validates both `image_version` values and digests, then runs `docker buildx imagetools
   create` from each `<repository>@<digest>` to that repository's `:latest` tag. Promotion does
   not rebuild, pull, or resolve a mutable tag.
3. The `publish` job waits for `create-release`, `app-image`, `web-image`, `desktop`, `updater-manifest`, and
   `promote-images`, then changes the draft release to published.

`promote-images` updates the two GHCR repositories one after the other, so the cross-repository
operation is not atomic: the app `:latest` update can succeed and the web update can then fail. A
failed image, desktop or updater-manifest job skips promotion and publication. Once
`create-release` has made the draft, any promotion or publish failure leaves that GitHub Release
draft/unpublished. If promotion fails, an update it already completed stays in place and `publish`
does not run. If the publish command fails, the release stays unpublished until the failure is
fixed and the workflow is retried.

### Desktop assets and latest.json

GitHub strips non-ASCII characters from asset names, which would reduce the product name 学道 to
nothing and leave names like `_1.4.6_x64.dmg` that no signature can be matched to. The desktop job
therefore names every asset with tauri-action's pattern
`xuedao_[version]_[platform]_[arch][setup][ext]`, which gives:

| Platform | Installer | Updater bundle (+ `.sig`) |
|---|---|---|
| macOS Apple Silicon | `xuedao_<ver>_darwin_aarch64.dmg` | `xuedao_<ver>_darwin_aarch64.app.tar.gz` |
| macOS Intel | `xuedao_<ver>_darwin_x64.dmg` | `xuedao_<ver>_darwin_x64.app.tar.gz` |
| Windows | `xuedao_<ver>_windows_x64-setup.exe`, `xuedao_<ver>_windows_x64.msi` | the same files |
| Linux | `xuedao_<ver>_linux_amd64.AppImage`, `xuedao_<ver>_linux_amd64.deb` | the same files |

The desktop builds do not write `latest.json` (`includeUpdaterJson: false`), because four matrix
jobs writing it at the same time overwrite each other. The `updater-manifest` job runs
`scripts/updater_manifest.py assemble` once instead. It:

1. lists the draft release's assets and fails, before downloading anything, if a required bundle
   or its `.sig` is missing. Required: `darwin-aarch64-app`, `darwin-x86_64-app`,
   `windows-x86_64-nsis`, `linux-x86_64-appimage`. The MSI and `.deb` entries are added when both
   files exist;
2. downloads each bundle and verifies its signature with `minisign` against
   `plugins.updater.pubkey` in `frontend/src-tauri/tauri.conf.json`, so a secret that does not match
   the committed public key fails the release;
3. writes `latest.json` with the CHANGELOG section for the version as release notes, the
   installer-specific keys and the fallback keys `darwin-aarch64`, `darwin-x86_64` and
   `windows-x86_64` (NSIS), then uploads it.

There is no plain `linux-x86_64` key on purpose. The updater tries `<os>-<arch>-<installer>`
first and then `<os>-<arch>`, so a `.deb` install with no `.deb` entry would otherwise be handed an
AppImage.

After flipping the draft, `publish` runs `scripts/updater_manifest.py verify`. It fetches
`releases/latest/download/latest.json`, checks the version, the required keys and that every URL
answers, retrying for about a minute. If the check still fails, the job puts the release back to
draft, which leaves the previous release as "latest", and fails.

### Desktop runners

The desktop matrix currently uses these runner labels:

- Linux: `ubuntu-22.04`
- Windows: `windows-latest`
- macOS Apple Silicon: `macos-latest`
- macOS Intel: `macos-15-intel`

macOS caveat: PyInstaller cannot cross-compile the sidecar, so the `x86_64-apple-darwin` build
runs on a native Intel `macos-15-intel` runner and `aarch64-apple-darwin` runs on the Apple
Silicon `macos-latest` runner.

## Updater signing keypair (free, one-time)

The Tauri auto-updater needs its own signing keypair. It is separate from OS code signing and
costs nothing. In `sweetcornna/university-helper` the `create-release` job fails with
"TAURI_SIGNING_PRIVATE_KEY is not set" when the secret is missing, because a release without signed
bundles cannot update installed apps. A fork without the secret still gets installers, built
unsigned, and its release has no `.sig` files and no `latest.json`.

The committed public key has the minisign key ID `1AA9710ADA25E6ED`. You only need the steps below
to create a new pair:

```bash
cd frontend
npm install                                   # ensures @tauri-apps/cli is available
npm run tauri signer generate -- -w ~/.tauri/uh-updater.key
#   (equivalent: npx @tauri-apps/cli@latest signer generate -w ~/.tauri/uh-updater.key)
```

The command asks whether to protect the private key with a password and writes:
- `~/.tauri/uh-updater.key`: the **private** key. Never commit it; it becomes a GitHub secret.
- `~/.tauri/uh-updater.key.pub`: the public key, which goes into `tauri.conf.json`.

Store the secrets and wire the public key:

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/uh-updater.key
# Set this only when the private key is password-protected; never echo the value.
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD
```

The private key in CI must match `plugins.updater.pubkey` in
`frontend/src-tauri/tauri.conf.json`. When you generate a new pair, update the public-key field and
the `TAURI_SIGNING_PRIVATE_KEY` secret together, and never pair a private key from one keypair with
the public key from another. The `updater-manifest` job catches a mismatch before anything is
published. `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` is only needed when the private key has a password;
the workflow passes it through to Tauri. You can check a key locally by signing a scratch file:

```bash
head -c 1024 /dev/urandom > /tmp/scratch.bin
( cd frontend && TAURI_SIGNING_PRIVATE_KEY_PASSWORD="" npx tauri signer sign -f ~/.tauri/uh-updater.key /tmp/scratch.bin )
```

If that succeeds with an empty password, leave the password secret unset. Keep `endpoints` at
`https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json`.

Whether the secrets are configured is repository and CI state. Check the key pair and the
resulting release assets each time you cut a release instead of recording their state here.

Checklist:
- [ ] `chmod 600 ~/.tauri/uh-updater.key`; the key and `.pub` live **outside** the repo and are never staged.
- [ ] `TAURI_SIGNING_PRIVATE_KEY` contains the private key matching `tauri.conf.json` `plugins.updater.pubkey`.
- [ ] If the private key is encrypted, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` is configured with its matching password.
- [ ] Every required updater bundle has a `xuedao_*.sig` next to it, and the `updater-manifest` job uploaded `latest.json`.
- [ ] `releases/latest/download/latest.json` returns the new version (the `publish` job checks this too).

## GHCR: make server images anonymously pullable (one-time)

This lets the one-click `deploy_server.sh` (and the §11 deploy fix-forward) run `docker pull`
without logging in.

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

Once both images pull anonymously, the reported `Invalid host header` / `dependency app failed
to start` deploy bug is fixed at the distribution level: a clean server running
`bash scripts/deploy_server.sh --tag v1.3.0` pulls the current fixed images. Those images always accept `localhost` and `127.0.0.1` in `AllowedHostsMiddleware`
(`backend/app/main.py`), so the container healthcheck does not get a 400. Other hostnames are
allowed when they appear in `CORS_ORIGINS` or in the comma-separated `ALLOWED_HOSTS` setting. A
rejected host gets a JSON 400 (`"code": "InvalidHost"`) that names `ALLOWED_HOSTS`.

## Code-signing status (free-first)

- **Linux**: no signing needed (`.AppImage`/`.deb`).
- **Windows**: we have applied to the free [SignPath Foundation](https://signpath.org/) OSS program.
  Until it is approved, builds are unsigned and SmartScreen shows "More info → Run anyway".
- **macOS**: builds are ad-hoc signed, so Gatekeeper needs "right-click → Open". An optional Apple
  Developer ID ($99/yr) for notarization is planned. The CI signing steps only run when their
  secrets exist, so adding them later needs no workflow change.
