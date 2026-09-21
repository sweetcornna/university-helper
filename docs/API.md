# API

Base URL: `https://shuake.cornna.xyz/api/v1` (production)
or `http://localhost:8000/api/v1` (local dev).

Every endpoint emits JSON. Errors use the shape:

```json
{ "code": "ErrorClassName", "message": "Human-readable text" }
```

For Pydantic validation failures (HTTP 422) FastAPI's default `detail`
array is returned; the frontend `utils/api.js` flattens it before
surfacing to the user.

Authoritative source: `backend/app/api/v1/`. When `DOCS_ENABLED=true` the
service also exposes Swagger UI at `/docs` and the raw spec at
`/openapi.json` — prefer those for live exploration.

---

## Authentication

All endpoints under `/api/v1/` (except those in `PUBLIC_ROUTES` in
`backend/app/config.py`) require:

```
Authorization: Bearer <jwt>
```

Tokens are HS256, signed with `SECRET_KEY`. Claims include
`user_id`, `tenant_db_name`, `iat`, `nbf`, `exp`, `jti`. Default lifetime
is `ACCESS_TOKEN_EXPIRE_MINUTES` (30 min).

### POST /auth/register

Create a new user, provision a tenant DB, return a token.

```json
// request
{ "username": "alice99", "email": "alice@example.com", "password": "Str0ngP@ss",
  "code": "<6-digit, required only when EMAIL_VERIFICATION_ENABLED>" }
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

Username must match `^[a-z0-9]+$`. Password must be ≥ 8 chars with at
least one uppercase, one lowercase, one digit.

When `EMAIL_VERIFICATION_ENABLED` is true the request must carry a `code`
obtained from `/auth/send-code`; a missing or wrong code is a 400. When the
flag is false (the default, and what the desktop build uses) the endpoint
behaves exactly as it always has and `code` is ignored.

### GET /auth/config

Public. Tells the SPA which auth features are switched on so it can decide
whether to render the verification-code field.

```json
{ "email_verification_enabled": true }
```

### POST /auth/send-code

Public. Emails a 6-digit verification code via SMTP. Rate-limited like the
other auth routes (5 req/60s per IP) plus a 60-second per-address resend
cooldown.

```json
// request
{ "email": "alice@example.com", "scene": "register" }
```

`scene` is `register` or `reset`.

- `register` — returns 400 `该邮箱已注册` for an address that already has an
  account, so the user is not sent a code they cannot use.
- `reset` — always returns `{"sent": true}`, whether or not the address is
  registered, so the endpoint cannot be used to enumerate users.

Returns 503 when `EMAIL_VERIFICATION_ENABLED` is false or SMTP is not
configured, 429 when the resend cooldown has not elapsed, and 502 when the
SMTP server rejects the message.

Codes are stored only as a SHA-256 hash, expire after 10 minutes, are
single-use, and are invalidated after 5 failed attempts.

### POST /auth/reset-password

Public. Consumes a `reset`-scene code and sets a new password.

```json
{ "email": "alice@example.com", "code": "123456", "new_password": "N3wStr0ng" }
```

Returns `{"reset": true}`. The new password must satisfy the same strength
rules as registration.

### POST /auth/login

```json
{ "email": "alice@example.com", "password": "Str0ngP@ss" }
```

Returns the same shape as `/register`.

### GET /auth/shuake-token

Returns a fresh 7-day compat token for clients that still use the
shuake bearer. Only works when `SHUAKE_COMPAT_SECRET` (≥ 32 chars) is
configured on the backend. Requires the regular JWT.

---

## Chaoxing

`backend/app/api/v1/chaoxing.py` — sign-in flow + Baidu location utils.

| Method | Path | Purpose |
|---|---|---|
| POST | `/chaoxing/login` | Phone-number + password login; primes the in-memory client cache. |
| GET | `/chaoxing/session` | Whether a stored session is usable (`active`, `username`, `expires_at`). Never returns cookies. |
| DELETE | `/chaoxing/session` | Forget the stored session ("switch account"). |
| POST | `/chaoxing/qr-login` | Begin a 学习通 QR login; returns a `session_id` and a base64 QR PNG. |
| GET | `/chaoxing/qr-login/{session_id}` | Poll one QR login (`pending` / `scanned` / `success` / `failed`). A refreshed `qr_code` rides back when the previous code expired, so a slow scan can still succeed. |
| DELETE | `/chaoxing/qr-login/{session_id}` | Cancel an in-flight QR login. |
| GET | `/chaoxing/courses` | List courses for the authenticated chaoxing client. |
| POST | `/chaoxing/sign` | Submit a sign-in for one active session. |
| POST | `/chaoxing/sign-all` | Submit sign-ins for every currently-active session. |
| GET | `/chaoxing/location/geocode` | Address → lat/lng (no auth). |
| GET | `/chaoxing/location/search` | Place keyword search (no auth). |
| GET | `/chaoxing/location/reverse-geocode` | lat/lng → address (no auth). |

The location endpoints are listed in `PUBLIC_ROUTES` so the frontend's
map picker can call them without a JWT.

**`password` is optional on the sign-in and task routes** (`/chaoxing/sign`,
`/chaoxing/sign-all`, `/chaoxing/class-sign`, `/chaoxing/start`,
`/chaoxing/class-start`, `/course/start`). When it is omitted the server reuses
a stored session, which is what lets 学习通签到 and 学习通泛雅 share one login.
The `username` stays required in every case: it is what binds a reused cookie
jar to an account, so omitting it fails rather than adopting an arbitrary
session. See `ChaoxingSigninManager._resolve_client`.

---

## Course tasks (Chaoxing Fanya + Zhihuishu)

`backend/app/api/v1/course.py` — long-running automation tasks.

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

Tasks store JSONB payloads in the user's tenant DB (`course_task_store`).
Long polling clients should use `status` + `logs` with backoff; the
canonical client is `frontend/src/pages/ChaoxingFanya.jsx` and
`Zhihuishu.jsx`.

---

## Observability

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Returns `{ "status": "ok\|degraded", "db": "ok", "cleanup_task": "alive\|dead" }`. Used by Docker healthchecks. |
| GET | `/metrics` | Plain-text Prometheus exposition (process uptime + per-path × status counter). |

---

## Rate limiting

- nginx: `/api/v1/auth/login` capped at 5 req/min per IP; `/api/` at 20 req/s burst 40.
- FastAPI middleware (`backend/app/middleware/rate_limiter.py`): per-route window counters with Postgres-backed storage and an in-memory fallback.
- 429 responses include `Retry-After` when emitted by nginx.

---

## OpenAPI

The full machine-readable schema is at `/openapi.json` when
`DOCS_ENABLED=true`. To regenerate a static copy for review without
running the app:

```bash
cd backend
python -c "from app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" \
  > ../docs/openapi.snapshot.json
```
