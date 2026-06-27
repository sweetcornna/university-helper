# 学道 desktop shell (Tauri v2)

Thin native shell that spawns the `uh-backend` sidecar (the PyInstaller-frozen
FastAPI backend from `backend/desktop_entry.py`), reads its
`UH_BACKEND_LISTENING <port>` readiness line, and opens a webview at
`http://127.0.0.1:<port>` — where the backend serves the SPA same-origin. The
sidecar is killed on exit; auto-update is wired to GitHub Releases.

## Layout
- `src/port.rs` — `parse_listening_port` (the unit-tested readiness parser).
- `src/lib.rs` — spawn sidecar → parse port → open loopback window → kill on exit + updater.
- `src/main.rs` — entrypoint.
- `tauri.conf.json` — bundle/updater config (`externalBin: binaries/uh-backend`, `frontendDist: splash`).
- `capabilities/default.json` — `core:default` + `updater:default` + scoped `shell:allow-spawn`.
- `binaries/` — the sidecar. CI drops `uh-backend-<triple>[.exe]` here (git-ignored); locally use the dev stub.

## Dev loop
1. `bash frontend/src-tauri/scripts/make-dev-sidecar.sh` (once per OS / after `cargo clean`) — writes
   `binaries/uh-backend-<host-triple>` from `dev-stub.py` (honors the readiness contract; serves a trivial page).
2. `cd frontend && npm install` (first time), then `npm run tauri dev`.
3. Splash shows → stub prints `UH_BACKEND_LISTENING <port>` → main window opens on the stub page.
4. For the **real** app, drop the workstream-D PyInstaller binary as `binaries/uh-backend-<triple>[.exe]`
   (`bash scripts/build_sidecar.sh` then rename to the triple from `rustc --print host-tuple`).

## Local gates
```bash
# parse_listening_port unit tests (no Tauri toolchain needed):
rustc --test --edition 2021 src/port.rs -o /tmp/uh_port_test && /tmp/uh_port_test
# formatting / lints / full unit run (needs icons + a triple-named sidecar present):
cargo fmt --manifest-path Cargo.toml --check
cargo clippy --manifest-path Cargo.toml --all-targets -- -D warnings
cargo test  --manifest-path Cargo.toml
# debug bundle smoke (override signing locally; real keys come from CI / workstream F):
bash scripts/make-dev-sidecar.sh
( cd .. && npm run tauri build -- --debug --config '{"bundle":{"createUpdaterArtifacts":false}}' )
```

## Icons
`tauri.conf.json` references `icons/*` (required by `generate_context!`). Generate the set from a
512×512+ source:
```bash
( cd frontend && npm run tauri icon src-tauri/icons/source.png )
```

## Notes
- `createUpdaterArtifacts: true` needs `TAURI_SIGNING_PRIVATE_KEY` at build time (CI / workstream F);
  the local smoke overrides it to `false`.
- `plugins.updater.pubkey` is a placeholder filled by workstream F's `tauri signer generate`.
- `version` (here + `Cargo.toml`) is stamped from the git tag by `scripts/set_version.sh`.
