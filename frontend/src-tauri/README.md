# 学道 desktop shell (Tauri v2)

A thin native shell around the local backend. It starts the `uh-backend` sidecar (the FastAPI
backend from `backend/desktop_entry.py`, frozen with PyInstaller), waits for the sidecar's
`UH_BACKEND_LISTENING <port>` readiness line, and opens a webview at `http://127.0.0.1:<port>`,
where the backend serves the SPA from the same origin. The shell stops the sidecar when the app
exits and checks GitHub Releases for updates.

## Layout
- `src/port.rs`: `parse_listening_port`, the unit-tested readiness parser.
- `src/lib.rs`: starts the sidecar, parses the port, opens the loopback window, stops the sidecar on exit, runs the update check and writes `desktop.log`.
- `src/main.rs`: entrypoint.
- `tauri.conf.json`: bundle and updater config (`externalBin: binaries/uh-backend`, `frontendDist: splash`).
- `capabilities/default.json`: `core:default` + `updater:default` + scoped `shell:allow-spawn`.
- `windows/hooks.nsh`: NSIS installer hooks (see [Notes](#notes)).
- `binaries/`: the sidecar. CI puts `uh-backend-<triple>[.exe]` here (git-ignored); locally use the dev stub.

## Dev loop
1. Run `bash frontend/src-tauri/scripts/make-dev-sidecar.sh` once per OS and again after
   `cargo clean`. It writes `binaries/uh-backend-<host-triple>` from `dev-stub.py`, which follows
   the readiness contract and serves a trivial page.
2. `cd frontend && npm install` (first time), then `npm run tauri dev`.
3. The splash shows, the stub prints `UH_BACKEND_LISTENING <port>`, and the main window opens on the stub page.
4. To run the **real** app, build the sidecar with `bash scripts/build_sidecar.sh` and copy it to
   `binaries/uh-backend-<triple>[.exe]`, using the triple from `rustc --print host-tuple`.

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

CI runs the same `cargo test --locked` in the `desktop-rust` job of `.github/workflows/test.yml`,
using the dev sidecar.

## Icons
`tauri.conf.json` references `icons/*`, which `generate_context!` requires. Generate the set from a
source image of at least 512×512:
```bash
( cd frontend && npm run tauri icon src-tauri/icons/source.png )
```

## Updates
About 8 seconds after launch the shell checks
`https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json`, with a
20 second timeout. If a newer version exists, a native dialog titled 学道有新版本 shows both
versions, the first 600 characters of the release notes and a warning that updating restarts the
app and interrupts running tasks. The buttons are 现在更新 and 稍后. 稍后 leaves the app alone until
the next launch. 现在更新 downloads and installs the update, stops the sidecar and restarts. If the
install fails, a 学道更新失败 dialog shows the error.

Updates are signed. `plugins.updater.pubkey` is the real public key, minisign key ID
`1AA9710ADA25E6ED`; the matching private key lives in the `TAURI_SIGNING_PRIVATE_KEY` repository
secret. See `docs/RELEASING.md` for how releases build and verify `latest.json`.

## Stopping the sidecar
The sidecar is a PyInstaller onefile binary, so it runs as two processes: a bootloader and the
Python child that serves the backend. Stopping only the bootloader would leave the child running
and keep the port and files busy, so the shell stops the whole tree:

- On macOS and Linux it sends SIGTERM (the bootloader forwards it so uvicorn can close `local.db`),
  waits up to 1.5 seconds, then kills the process.
- On Windows it runs `taskkill /PID <pid> /T /F` without opening a console window.

This happens when the app exits, when startup fails, and right before the updater exits the app to
run an installer.

The backend protects itself as well. The shell passes its own PID in `UH_PARENT_PID`, and
`desktop_entry.py` then:

- checks every second whether that process is gone (or, on POSIX, whether the backend has been
  re-parented) and shuts down if so. On POSIX it asks uvicorn to stop and forces the exit after 5
  seconds; on Windows it exits at once;
- records itself in `uh-backend.pid` in the app data directory. On the next start it stops a
  backend recorded there if that backend's parent is gone and its executable is `uh-backend`;
- in packaged POSIX builds, also stops `uh-backend` processes that were re-parented to init, which
  earlier 1.4.x releases could leave behind.

## Notes
- `createUpdaterArtifacts: true` needs `TAURI_SIGNING_PRIVATE_KEY` at build time. CI provides it;
  the local smoke build above turns updater artifacts off.
- `windows/hooks.nsh` (wired through `bundle.windows.nsis.installerHooks`) runs
  `taskkill /F /T /IM uh-backend.exe` before the NSIS installer copies files and before the
  uninstaller removes them. The installer only waits for the main executable, and a backend still
  running from the previous version would keep its files locked.
- The shell writes `desktop.log` to the app log directory: `~/Library/Logs/xyz.cornna.shuake/` on
  macOS, `%LOCALAPPDATA%\xyz.cornna.shuake\logs\` on Windows, `~/.local/share/xyz.cornna.shuake/logs/`
  on Linux. Once the file grows past 1 MB it is renamed to `desktop.log.1` and a new one starts.
  Release builds on Windows have no console, so this file is where startup and update errors show up.
- `version` (here and in `Cargo.toml`) is stamped from the git tag by `scripts/set_version.sh`.
