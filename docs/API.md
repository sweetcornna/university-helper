# API

Base URL: `https://shuake.cornna.xyz/api/v1` (production)
or `http://localhost:8000/api/v1` (local dev).

Every endpoint returns JSON. Errors use this shape:

```json
{ "code": "ErrorClassName", "message": "Human-readable text" }
```

Pydantic validation failures (HTTP 422) return FastAPI's default `detail`
array instead; the frontend `utils/api.js` flattens it before showing it to
the user. Unexpected server errors return 500 with
`{ "code": "InternalServerError", "message": "Internal server error" }`, and
the real cause is only in the server log.

The route code in `backend/app/api/v1/` is the source of truth. When
`DOCS_ENABLED=true` the service also serves Swagger UI at `/docs` and the raw
spec at `/openapi.json`, which are easier for exploring a running instance.

## Authentication

All endpoints under `/api/v1/` (except those in `PUBLIC_ROUTES` in
`backend/app/config.py`) require:

```
Authorization: Bearer <jwt>
```

Tokens are HS256, signed with `SECRET_KEY`. Claims include
`user_id`, `tenant_db_name`, `iat`, `nbf`, `exp`, `jti`. Default lifetime
is `ACCESS_TOKEN_EXPIRE_MINUTES` (30 min).

The desktop app runs the backend with `PROFILE=local` and has no accounts.
There, every `/auth/*` route returns 409:

```json
{ "code": "LocalProfileAuthUnavailable", "message": "桌面版不需要注册或登录，直接使用即可" }
```

### GET /runtime

Public. Tells the SPA whether it has to show the login page.

```json
{ "profile": "server", "requires_auth": true }
```

The desktop build returns `"profile": "local"` and `"requires_auth": false`.

### POST /auth/register

Create a new user, provision a tenant DB, return a token.

```json
// request
{ "username": "alice99", "email": "alice@example.com", "password": "Str0ngP@ss" }
```

```json
// response (201)
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user_id": 42,
  "tenant_db_name": "tenant_alice99",
  "shuake_token": "<optional, only if SHUAKE_COMPAT_SECRET is set>"
}
```

Username must be 3 to 30 characters matching `^[a-z0-9]+$`. Password must be
≥ 8 chars with at least one uppercase, one lowercase, one digit.

Errors:

| Status | When |
|---|---|
| 422 | Validation failed, including the reserved usernames `template`, `template0`, `template1`, `postgres`, `main`, `maindb`, `root` and `system`. |
| 400 | Other registration errors with a user-facing message, such as an email that is already registered. |
| 503 `DatabaseNotInitializedError` | The server's database is missing the `users` table or the `tenant_template` database. An administrator needs to check `/health` and the server log. |
| 503 `TenantProvisioningError` | The tenant database could not be created: the template stayed busy after several retries, the database role lacks `CREATEDB`, or Postgres could not be reached. |

Both 503 errors are subclasses of `ServiceUnavailableError`, and their
`message` explains the problem in Chinese.

### POST /auth/login

```json
{ "email": "alice@example.com", "password": "Str0ngP@ss" }
```

Returns the same shape as `/register`.

### GET /auth/shuake-token

Returns a fresh 7-day compat token for clients that still use the
shuake bearer. It only works when `SHUAKE_COMPAT_SECRET` (≥ 32 chars) is
configured on the backend, and requires the regular JWT.

## Chaoxing

`backend/app/api/v1/chaoxing.py` handles the sign-in flow and the Baidu location helpers.

| Method | Path | Purpose |
|---|---|---|
| POST | `/chaoxing/login` | Phone-number + password login; primes the in-memory client cache. |
| GET | `/chaoxing/courses` | List courses for the authenticated chaoxing client. |
| POST | `/chaoxing/sign` | Submit a sign-in for one active session. |
| POST | `/chaoxing/sign-all` | Submit sign-ins for every currently-active session. |
| GET | `/chaoxing/location/geocode` | Address → lat/lng (no auth). |
| GET | `/chaoxing/location/search` | Place keyword search (no auth). |
| GET | `/chaoxing/location/reverse-geocode` | lat/lng → address (no auth). |

The location endpoints are listed in `PUBLIC_ROUTES` so the frontend's
map picker can call them without a JWT.

## Course tasks (Chaoxing Fanya + Zhihuishu)

`backend/app/api/v1/course.py` runs the long-running automation tasks.

| Method | Path | Purpose |
|---|---|---|
| POST | `/course/start` | Start a course-learning task (`platform: "chaoxing"` or `"zhihuishu"`). |
| GET | `/course/status/{task_id}` | Poll task progress. |
| GET | `/course/tasks` | List the current user's tasks. |
| GET | `/course/logs/{task_id}` | Stream log lines for one task. |
| POST | `/course/task/{task_id}/pause` | Pause a running task. |
| POST | `/course/task/{task_id}/resume` | Resume a paused task. |
| POST | `/course/task/{task_id}/stop` | Cancel a task. |
| POST | `/course/zhihuishu/qr-login` | Begin Zhihuishu QR login; returns a session id and a QR PNG. |
| POST | `/course/zhihuishu/password-login` | Zhihuishu phone + password login. |
| POST | `/course/zhihuishu/tasks/course` | Enqueue a Zhihuishu course-learning task. |
| GET | `/course/zhihuishu/tasks/{task_id}` | Read a task and its per-lesson results, including lessons awaiting human verification. |
| POST | `/course/zhihuishu/tasks/{task_id}/refresh-verification` | Query platform completion for deferred lessons without submitting learning progress. Returns the updated task; unknown tasks return 404. |
| POST | `/course/zhihuishu/resume` | Recheck deferred lessons and resume the current paused Zhihuishu task. |

Chaoxing tasks store JSONB payloads in the user's tenant DB (`course_task_store`).
Zhihuishu tasks and their deferred-lesson lists are held in the current user's
adapter memory and reset when the service restarts. The task/progress field
`verification_required` counts lessons with `status: "needs_verification"`.
These lessons are excluded from both `completed` and `failed`; a completed task
can mean its automatic pass ended with manual work outstanding. Two consecutive
platform verification requests pause the task when unfinished lessons remain.
Only platform `watchState=1` moves a deferred lesson to `completed`; refreshing
again does not increment its count twice. Verification is completed in the
official player by the user, and refresh/resume never solves a CAPTCHA.

Polling clients should call `status` and `logs` with backoff. See
`frontend/src/pages/ChaoxingFanya.jsx` and `Zhihuishu.jsx` for the reference
client.

## System (server edition only)

`backend/app/api/v1/system.py`. This router is not mounted in the desktop
build.

### GET /system/update

Tells an administrator whether a newer release exists. Requires the regular
JWT. Returns 403 (`Administrator only`) for everyone else.

Administrators are the accounts whose email is listed in `ADMIN_EMAILS`
(comma separated, case-insensitive). If `ADMIN_EMAILS` is empty, the account
with the smallest `users.id` is the administrator.

```json
// response (200)
{
  "enabled": true,
  "current": "1.4.6",
  "latest": "1.4.7",
  "has_update": true,
  "html_url": "https://github.com/sweetcornna/university-helper/releases/tag/v1.4.7",
  "notes": "<release notes, at most 2000 characters>",
  "published_at": "<ISO 8601 timestamp from GitHub>",
  "checked_at": "<ISO 8601 timestamp of the last successful check>",
  "commands": {
    "bash": "bash scripts/deploy_server.sh --tag 1.4.7 -y",
    "powershell": "pwsh scripts/deploy_server.ps1 -Tag 1.4.7 -Yes"
  }
}
```

The server fetches the GitHub Releases API (`UPDATE_CHECK_URL`) in the
background and ignores drafts and prereleases. Until a check has succeeded,
`latest`, `html_url`, `published_at`, `checked_at` and `commands` are `null`
and `has_update` is `false`. With `UPDATE_CHECK_ENABLED=false` the response is
only `{ "enabled": false, "current": "<version>", "has_update": false }`.

## Observability

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Returns `{ "status": "ok\|degraded", "db": "ok", "cleanup_task": "alive\|dead", "schema": "ok\|missing_users\|missing_tenant_template\|unknown" }`. Used by Docker healthchecks. |
| GET | `/metrics` | Plain-text Prometheus exposition (process uptime + per-path × status counter). |

`/health` returns 503 when the database does not answer. The `schema` field
only appears on the server edition with Postgres. Any value other than `ok`
sets `status` to `degraded` but keeps the 200 status code, so the container
stays up while registration is broken. Check this field first when
registration fails.

## Rate limiting

- nginx: `/api/v1/auth/login` capped at 5 req/min per IP; `/api/` at 20 req/s burst 40.
- FastAPI middleware (`backend/app/middleware/rate_limiter.py`): per-route window counters with Postgres-backed storage and an in-memory fallback.
- 429 responses include `Retry-After` when emitted by nginx.

## Host header

Requests whose `Host` header is not `localhost`, `127.0.0.1`, a host from
`CORS_ORIGINS` or a name in `ALLOWED_HOSTS` get 400 with code `InvalidHost`.
The message names the rejected host and the `ALLOWED_HOSTS` setting.

## OpenAPI

The full machine-readable schema is at `/openapi.json` when
`DOCS_ENABLED=true`. To regenerate a static copy for review without
running the app:

```bash
cd backend
python -c "from app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" \
  > ../docs/openapi.snapshot.json
```
