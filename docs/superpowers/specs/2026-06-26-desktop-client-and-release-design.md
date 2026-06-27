# Design — Fully-local Tauri desktop client + cross-platform release (v1.4.0)

- **Date:** 2026-06-26
- **Status:** Draft for review
- **Scope this cycle:** Windows / macOS / Linux desktop client (fully local, no Docker, no server) + a real cross-platform GitHub Release with auto-update.
- **Deferred (later cycles):** Android client; unifying the *server* path onto the storage interface; unattended/background runs.

---

## 1. Summary

Ship University Helper as a **downloadable desktop app** that runs entirely on the user's machine — no Docker, no server, no terminal. A [Tauri v2](https://v2.tauri.app) native window spawns the existing FastAPI backend, **frozen into a single binary with PyInstaller**, on `127.0.0.1`. That backend serves the existing React SPA **same-origin** and stores everything in an **embedded SQLite file** in the OS app-data dir. Tasks run only while the app is open (an accepted constraint).

The existing **Postgres / multi-tenant server deployment stays byte-for-byte unchanged**: the local single-user path is added *alongside* it behind a profile flag, not by rewriting the server.

This cycle also fixes the reported Docker deploy failure (`Invalid host header` → `dependency app failed to start`) by fixing the release-image pipeline (root cause analysis in §11).

---

## 2. Goals / Non-goals

### Goals
1. One-download, double-click desktop app for Windows, macOS (Intel + Apple Silicon), and Linux.
2. No external dependencies for the end user (no Docker, no Postgres, no Python install).
3. Auto-update from GitHub Releases.
4. Existing server deployment and its tests keep passing unchanged.
5. A release pipeline that builds desktop apps **and** server images from one git tag, with a single source-of-truth version.

### Non-goals (this cycle)
- Android / iOS clients.
- Refactoring the *server* request path onto the new storage interface (only the parts the **local** app exercises are abstracted now).
- Background/unattended execution when the app is closed.
- Paid OS code-signing (ship unsigned/ad-hoc; wire CI so it can be added later).

---

## 3. Background — key facts established from the code

All verified by read-only investigation (file:line evidence retained):

1. **The multi-tenant machinery is dead code for app data.** Every `get_db_session()` call passes no `db_name`, so all reads/writes hit `main_db`; `get_db()`/`get_tenant_db_connection` are never wired. `CREATE DATABASE … TEMPLATE` and the `todos/attachments/sessions` template tables are unused scaffolding. (`backend/app/db/session.py:161-188`, `backend/app/dependencies.py`, `database/templates/tenant_template.sql`.)
2. **The only live schema is 4 tables in one DB:** `users`, `rate_limit_counters` (`database/00-schema.sql:4-47`), and `course_task_store` + `course_task_history` created lazily in code (`backend/app/services/course/task_store.py:96-137`). The **local app only exercises** `course_task_store`, `course_task_history`, and a `/health` `SELECT 1` — it never logs in, so `users`/auth/rate-limit/tenant code is bypassed.
3. **All DB access funnels through one helper** `get_db_session()` and three modules: `task_store.py`, `auth_service.py`, `rate_limiter.py`. No runtime ORM; raw psycopg2 + Postgres-specific SQL.
4. **Credentials are not a table** — sensitive fields are Fernet-encrypted in-place inside the JSONB `payload` of the task tables, keyed by `CREDENTIAL_ENCRYPTION_KEY` (`backend/app/core/credential_crypto.py`, `task_store.py:20-79`).
5. **Auth is two independent JWT paths:** `tenant_isolation_middleware` (a gate whose `request.state.user_id` is never read) at `main.py:107`, and FastAPI deps `get_current_user` (auto_error=True, used by `course.py`) / `get_current_user_id` (auto_error=False, used by `chaoxing.py`) at `backend/app/dependencies.py:15,24`. Handlers only need an opaque `user_id` string ≤64 chars — **a constant works**.
6. **Backend is already PyInstaller-aware** — `cxsecret_font.resource_path()` reads `sys._MEIPASS` (`backend/app/services/course/chaoxing/cxsecret_font.py:31-63`).
7. **Frontend API base is relative** `'/api/v1'` by default (`frontend/src/utils/api.js:3-6`) → same-origin serving needs no frontend rebuild flags.
8. **No headless browser, no broker/scheduler** — automation is pure HTTP + in-process daemon threads; single-process friendly.

---

## 4. Architecture

```
 Tauri window (Rust, src-tauri/)             frozen Python sidecar (PyInstaller)
 ───────────────────────────────             ─────────────────────────────────────
 setup():                                    desktop_entry.py:
   spawn sidecar (shell plugin)   ──stdout──►   • resolve OS app-data dir (platformdirs)
   parse "UH_BACKEND_LISTENING <p>"             • generate+persist SECRET_KEY + fernet.key
   WebviewWindow → http://127.0.0.1:<p>         • point cookies/cache/local.db at app-data
   kill child on RunEvent::ExitRequested        • PROFILE=local, STORAGE_BACKEND=sqlite,
 capabilities: shell:allow-spawn(uh-backend)      ENFORCE_HTTPS=false, CORS=[127.0.0.1:p]
 plugins: updater (latest.json, pubkey)         • pick free port → print token → uvicorn
                                                          │  (asyncio loop, h11, workers=1)
                                                FastAPI app (PROFILE=local):
                                                  • tenant_isolation middleware SKIPPED
                                                  • dependency_overrides → user_id="local"
                                                  • StaticFiles serves frontend/dist  ← same origin
                                                  • Storage factory → SQLite TaskStore + DbProbe
```

Data flow: webview makes normal same-origin `fetch` to `/api/v1/...` on the loopback backend (no CORS, no Tauri IPC). The backend runs the existing chaoxing/zhihuishu HTTP automation in daemon threads, persisting task state to the local SQLite file.

---

## 5. Workstream A — Storage abstraction (scoped to what local needs)

**New package `backend/app/storage/`:**
- `base.py` — `Protocol`s: `TaskStore` (the existing public surface of `task_store.py`: `ensure_tables`, `upsert_task`, `get_task`, `list_tasks`, `append_history`, `list_history`) and `DbProbe` (`ping() -> bool` for `/health`).
- `postgres.py` — adapter that executes **today's exact SQL** via the existing `get_db_session()` (zero behavior change for the server).
- `sqlite.py` — adapter over one SQLite file: one `sqlite3.Connection(check_same_thread=False)`, `PRAGMA journal_mode=WAL` + `busy_timeout`, a `threading.Lock` serializing writes (daemon threads write often), `row_factory` → **plain dicts** (existing code calls `row.get()`).
- `factory.py` — `get_storage()` process-singleton chosen by `STORAGE_BACKEND` env (`postgres` default).

**Refactor** `task_store.py` and the `/health` probe (`main.py:205-226`) to call the storage adapter instead of embedding SQL. Credential encrypt/decrypt stays in `task_store`/`credential_crypto` unchanged (both adapters store the same encrypted JSON string).

**Postgres → SQLite SQL mapping (from investigation):**
| Postgres | SQLite action |
|---|---|
| `ThreadedConnectionPool` + `RealDictCursor` | one WAL connection + write lock; return plain dicts |
| `SERIAL`/`BIGSERIAL` | `INTEGER PRIMARY KEY` |
| `TIMESTAMPTZ` / `NOW()` | TEXT ISO-8601 UTC; bind `datetime.isoformat()` (py3.12 has no default datetime adapter) |
| `JSONB` + `Json()` | TEXT; `json.dumps`/`json.loads` in the adapter |
| `ON CONFLICT … DO UPDATE … EXCLUDED` | identical syntax (SQLite ≥3.24), drop `NOW()` |
| `RETURNING id` | `cursor.lastrowid` (RETURNING availability varies by linked SQLite) |
| `ORDER BY … DESC NULLS LAST` | `ORDER BY (col IS NULL), col DESC` |

**Tests (TDD):** a shared **contract test** runs against both adapters (Postgres adapter in CI with a service container, SQLite adapter in-memory/file) asserting identical observable behavior for upsert/get/list/history/prune. SQLite concurrency test: N daemon threads writing task updates without `database is locked`.

---

## 6. Workstream B — `APP_PROFILE=local`

- **Config** (`backend/app/config.py`): add `PROFILE: Literal["server","local"] = "server"` and module constant `LOCAL_USER_ID = "local"`. Default keeps existing deployments on the server path.
- **App factory** (`backend/app/main.py`): guard the single auth-bearing middleware —
  ```python
  if settings.PROFILE != "local":
      app.middleware("http")(tenant_isolation_middleware)  # current line 107
  ```
  All other middleware (metrics / https-redirect / security-headers / TrustedHost / CORS) stay registered — they are auth-agnostic.
- **Implicit local user via dependency overrides** (in the `local` branch) — **no edits to routers or `dependencies.py`**:
  ```python
  app.dependency_overrides[get_current_user]    = lambda: {"user_id": LOCAL_USER_ID}
  app.dependency_overrides[get_current_user_id] = lambda: LOCAL_USER_ID
  ```
  This makes the `HTTPBearer` sub-dependencies never run, so no `Authorization` header is required. `course.py`/`chaoxing.py` get `"local"` and work unchanged.
- **Env the launcher injects** so import-time validators (`config.py:58-70`) don't block boot: `SECRET_KEY` (persisted random ≥32), `CORS_ORIGINS=["http://127.0.0.1:<port>"]` (JSON), `ENV=dev` (so `CREDENTIAL_ENCRYPTION_KEY` is optional and the prod https/CORS gate is skipped), **`ENFORCE_HTTPS=false`** (default True would 301-loop the loopback), `STORAGE_BACKEND=sqlite`.

**Server path preservation:** the only diff server-mode sees is the new `PROFILE` field (default `"server"`) and a guard that is false in server mode. Server runtime behavior is unchanged.

**Tests:** local-profile app returns 200 (not 401) on a course endpoint with no token; server-profile app still 401s; `/health` green on SQLite.

---

## 7. Workstream C — FastAPI serves the SPA (same origin)

- Mount **after** all routers (`main.py:197`), so `/api/*`, `/health`, `/docs` win:
  ```python
  app.mount("/assets", StaticFiles(directory=DIST/"assets"), name="assets")

  @app.get("/{full_path:path}")
  async def spa(full_path: str):
      candidate = (DIST/full_path).resolve()
      if full_path and candidate.is_file() and DIST.resolve() in candidate.parents:
          return FileResponse(candidate)
      return FileResponse(DIST/"index.html")
  ```
- **Repoint `GET /`** (`main.py:200-202` currently returns JSON `{"message": "University Helper API"}`) — it would shadow `index.html`. In local mode it returns `index.html`; server mode can keep JSON (guard or just let the catch-all handle it).
- `DIST` resolves via the `_MEIPASS`-aware resource helper (frozen) or repo path (dev).
- Static/SPA paths pass freely in local mode because `tenant_isolation_middleware` is skipped (§6). The relative `/api/v1` base (incl. the 3 hardcoded-path files) works because everything is same-origin.
- PWA service worker (`frontend/dist/sw.js`, Workbox) is served as a real file by the catch-all; use a cache-busting/`updateViaCache:'none'` strategy so updates aren't masked by stale SW cache.

**Tests:** in local mode, `/` and an unknown client route return `index.html`; `/api/v1/...` still routes to the API; `/assets/...` serves the hashed asset.

---

## 8. Workstream D — sidecar launcher + PyInstaller freeze

**`backend/desktop_entry.py`** (the frozen entrypoint): resolve OS app-data dir via `platformdirs` (`%APPDATA%` / `~/Library/Application Support` / `~/.local/share`); generate + persist (0600) `SECRET_KEY` and a Fernet `CREDENTIAL_ENCRYPTION_KEY`; set `CHAOXING_COOKIES_FILE`/`CHAOXING_CACHE_FILE` and the SQLite path under app-data; `os.chdir(app_data)` so `answer_base.py:15`'s CWD-relative `config.ini` lookup resolves; set the local env (§6) **before importing `app.config`**; pick a free loopback port; `print("UH_BACKEND_LISTENING <port>", flush=True)`; `uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, workers=1, loop="asyncio", http="h11")`.

**PyInstaller spec:**
- Collect both first-party packages: `--collect-submodules app --collect-submodules api` (the `api/` package is a legacy import shim used by string-level `from api.* import …`).
- Data: `--add-data "frontend/dist:frontend/dist"`; optional `resource/font_map_table.json` if the font-decode feature is wanted (absent today → degrades gracefully).
- Compiled/lazy deps: `--collect-all lxml`, `--collect-submodules Crypto` (pycryptodome), `--collect-submodules fontTools`, `--collect-all bcrypt`, verify `cryptography`/`pydantic-core` `.so/.pyd`; `--hidden-import pyaes`. **Never `--loop uvloop`** (absent on Windows) → asyncio + h11.
- SQLite local build need not import psycopg2 if the storage factory imports `postgres.py` lazily; keep the Postgres import out of the local hot path.

**Smoke test (per OS, in CI):** launch the frozen binary, wait for the stdout token, `curl http://127.0.0.1:<port>/health` == 200. A green build ≠ a booting app, so this gate is mandatory.

---

## 9. Workstream E — Tauri v2 shell (`frontend/src-tauri/`)

- **`tauri.conf.json`:** `productName`, version (stamped from tag), `bundle.active`, `bundle.targets: ["msi","nsis","dmg","app","appimage","deb"]`, `bundle.externalBin: ["binaries/uh-backend"]`, `bundle.createUpdaterArtifacts: true`, `plugins.updater.{pubkey,endpoints}`, `app.security.csp` left to FastAPI (loopback page).
- **Sidecar binary naming:** ship `binaries/uh-backend-<target-triple>[.exe]` (e.g. `uh-backend-x86_64-pc-windows-msvc.exe`); CI renames the PyInstaller output to the triple from `rustc --print host-tuple`.
- **`src-tauri/src/lib.rs`:** in `setup()` spawn the sidecar (`tauri-plugin-shell`), read `CommandEvent::Stdout`, parse `UH_BACKEND_LISTENING <port>`, build `WebviewWindow` at `WebviewUrl::External(http://127.0.0.1:<port>)`; store `CommandChild` in managed state and **`child.kill()` on `RunEvent::ExitRequested`** (the Tauri footgun: sidecars are not auto-reaped). Optional `/health` poll as belt-and-suspenders.
- **Capabilities** (`src-tauri/capabilities/default.json`): `core:default`, `updater:default`, and `shell:allow-spawn` scoped to `{ name: "binaries/uh-backend", sidecar: true, args: … }`.
- **Loading model:** loopback URL (same-origin) — no CORS, no IPC perms, no duplicated frontend bundle. `build.frontendDist` points at a tiny placeholder/splash; the real window is created at runtime once the port is known.
- **Updater:** `tauri-plugin-updater` v2; keypair via `tauri signer generate` (free); `latest.json` at `releases/latest/download/latest.json`; Rust-side `check()/download_and_install()` then `app.restart()` (ensure the sidecar is killed first so the port is free on restart).

**Process-lifecycle note:** PyInstaller `--onefile` is a bootloader that spawns a child; on some platforms killing the parent may not reap the grandchild. Mitigations: prefer process-group kill, or have the sidecar self-exit when its parent/stdin closes. (Onefile vs onedir is an open implementation decision — see §16.)

---

## 10. Workstream F — release pipeline (`.github/workflows/release.yml`)

Single workflow, fan-out from one `v*` tag (tag = single source of truth):

1. **`create-release`** (ubuntu): resolve `version` from the tag; run new **`scripts/set_version.sh "$VERSION"`** to stamp `frontend/package.json`, `backend/pyproject.toml`, `backend/app/main.py:73`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml` (eliminates today's 4-place manual drift); extract CHANGELOG notes; create a **draft** release (so matrix legs attach to one release).
2. **`images`** (ubuntu, needs create-release): today's job unchanged — buildx multi-arch app+web → GHCR `:version` and `:latest`.
3. **`desktop`** (matrix, needs create-release): `windows-latest`, `macos-latest` ×2 (`aarch64`/`x86_64-apple-darwin`), `ubuntu-22.04` (pins `libwebkit2gtk-4.1`). Each: stamp version → setup Python 3.11 + `pip install -r backend/requirements.txt pyinstaller` → build sidecar → **smoke-test `/health`** → setup Node 20 + `npm ci && npm run build` → setup Rust + cache → rename sidecar to target triple → `tauri-apps/tauri-action@v0` (`projectPath: frontend`, `releaseId`) builds `.msi/.dmg/.AppImage` + updater `.sig`/`latest.json`.
4. **`publish`** (needs images + desktop): flip the release to published only when every leg succeeds (keeps GHCR `:latest`, the updater `latest.json`, and the GitHub "latest release" mutually consistent).

**Signing secrets are optional** — gate signing steps on `secrets.* != ''` so forks/contributors still get unsigned builds. Wire: `TAURI_SIGNING_PRIVATE_KEY(_PASSWORD)` (updater, free); macOS `APPLE_*` (notarization, later); Windows `WINDOWS_CERTIFICATE` / SignPath (later).

**GHCR fix:** ensure `Settings → Actions → Workflow permissions = Read and write`; re-run release on `v1.3.0` to (re)publish images; **make `university-helper-app` and `-web` packages Public** (one-time UI action or a PAT `gh api -X PATCH /user/packages/container/… -f visibility=public`). Then the one-click installer's anonymous `docker pull` works.

---

## 11. The reported Docker deploy bug (fix-forward)

**Root cause (high confidence):** `web` waits on `app` being `service_healthy`; the `app` healthcheck hits `http://localhost:8000/health` (Host `localhost`); pre-v1.1.0 code passed full CORS origin URLs as `TrustedHostMiddleware` host patterns, so bare `localhost` never matched → every request (incl. the healthcheck) → 400 `Invalid host header` → app never healthy → compose aborts `web` ("dependency app failed to start"). Current code (`backend/app/main.py:81-91`) already always seeds `localhost`/`127.0.0.1`, so the failing box is running a **stale/unpublished image**.

**Immediate fix (user runs on the deploy host):**
```bash
docker logs shuake-easy-learning-app --tail 50      # confirm "Invalid host header"
docker compose -p university-helper -f docker-compose.release.yml down
bash scripts/deploy_server.sh --build               # build from current fixed source
```
**Durable fix (in this cycle):** the §10 GHCR republish + make-public steps ensure `pull` mode serves the fixed image.

---

## 12. Versioning & rollout

- Git tag `vX.Y.Z` is the single source of truth; `scripts/set_version.sh` propagates it to all manifests at build time.
- First desktop release: `v1.4.0`.
- Server users are unaffected (server path unchanged); they keep using Docker/GHCR.

---

## 13. Testing strategy (TDD)

- **Storage:** shared contract test across Postgres + SQLite adapters; SQLite concurrency test.
- **Profile:** local vs server auth behavior; `/health` on SQLite; SPA catch-all routing.
- **Launcher:** unit-test env/path setup; integration smoke (boot frozen binary → `/health`).
- **CI:** existing backend/frontend test suites stay green (server path untouched); per-OS desktop smoke gate.
- Write tests before implementation for each unit; no success claim without running the command and seeing output.

---

## 14. Risks & mitigations

1. **SQLite concurrency** under daemon-thread writes → WAL + `busy_timeout` + write lock (tested).
2. **PyInstaller completeness** (hidden imports/data) → per-OS `/health` smoke gate; explicit collect flags.
3. **`config.ini` CWD lookup** (`answer_base.py:15`) → launcher `chdir` to app-data.
4. **Service-worker stale cache** in the webview → cache-busting/`updateViaCache:'none'`.
5. **Sidecar orphan / restart port clash** → kill on `ExitRequested`; kill before updater restart.
6. **Unsigned-build warnings** → README "right-click → Open" (macOS) / "more info → run anyway" (Windows); pursue free SignPath + optional $99 Apple later; CI ready for secrets.
7. **Tauri/Rust adds CI time + maintenance surface** → cached Rust toolchain; pinned webkit2gtk on ubuntu-22.04.

---

## 15. Deferred / future
- **Android** — thin wrapper (Tauri-mobile or Capacitor) pointing at a server URL; depends on the maintained server version.
- **Server unification** — move the server request path onto the full Storage interface (users/tenants/rate-limit) so both clients share one core end-to-end.
- **Unattended runs** — only if a hosted/always-on model is desired (changes the local-only premise).

---

## 16. Resolved decisions (confirmed 2026-06-26)
1. **App identity:** display name **学道** (English "University Helper"); bundle identifier **`xyz.cornna.shuake`**.
2. **PyInstaller packaging:** **`--onefile`** (revisit only if startup proves slow).
3. **Windows free signing:** pursue the **SignPath Foundation** OSS program in parallel; ship unsigned (SmartScreen "run anyway") until approved. macOS ad-hoc + "right-click → Open"; optional $99/yr Apple ID later. Updater keypair is free.
