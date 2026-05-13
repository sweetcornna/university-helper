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

Username must match `^[a-z0-9]+$`. Password must be ≥ 8 chars with at
least one uppercase, one lowercase, one digit.

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
| GET | `/chaoxing/courses` | List courses for the authenticated chaoxing client. |
| POST | `/chaoxing/sign` | Submit a sign-in for one active session. |
| POST | `/chaoxing/sign-all` | Submit sign-ins for every currently-active session. |
| GET | `/chaoxing/location/geocode` | Address → lat/lng (no auth). |
| GET | `/chaoxing/location/search` | Place keyword search (no auth). |
| GET | `/chaoxing/location/reverse-geocode` | lat/lng → address (no auth). |

The location endpoints are listed in `PUBLIC_ROUTES` so the frontend's
map picker can call them without a JWT.

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
