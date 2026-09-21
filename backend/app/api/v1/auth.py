import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.config import settings
from app.core import mailer
from app.db.session import get_db_session
from app.dependencies import get_current_user
from app.middleware.rate_limiter import rate_limiter
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SendCodeRequest,
    TokenResponse,
)
from app.services import email_verification
from app.services.auth_service import AuthService

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)

# Wall-clock pad, in seconds, applied to BOTH branches of a `reset` send-code
# request. The unknown-address branch does no work beyond a single indexed
# SELECT, so without the pad it would return in microseconds — a response-time
# oracle for "is this email registered". Padding only the skipped branch would
# just invert the oracle (a fast send would become the tell), so both branches
# are held to the same value. Same intent as the dummy bcrypt verification in
# AuthService.login_user.
#
# For this to be a real budget rather than a lower bound, the reset branch must
# not do anything of unbounded duration before responding. That is why the
# actual SMTP submission is handed to a BackgroundTask (see send_code): an
# Aliyun DirectMail round-trip routinely costs 0.5-3s and is capped only by the
# mailer's 10s socket timeout, so awaiting it inline would push the known-email
# branch past the pad and reopen the oracle.
_RESET_SEND_FLOOR_SECONDS = 1.0

# Per-IP DAILY cap on /auth/send-code, on top of the shared 5-req/60s auth
# limiter. Without it a single IP can drive ~7,200 messages/day through the
# operator's SMTP account at arbitrary attacker-chosen recipients, which burns
# the sending domain's reputation.
#
# 50 is chosen to be far below any volume that damages deliverability while
# staying above realistic legitimate use: a genuine user needs 1-2 codes to
# register and 1-2 to reset, and campus/NAT egress means dozens of real students
# can share one public IP. It is a 144x reduction in the worst case.
_SEND_CODE_DAILY_LIMIT = 50


def _mask_email(email: str) -> str:
    """Mask email for safe logging: user@example.com -> u***@example.com"""
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[0]}***@{domain}" if local else f"***@{domain}"


# NOTE on error handling: AuthService raises only plain ValueError for
# validation/credential failures, and lets genuine DB driver errors propagate
# to the global Exception handler in app.main (-> 500). The previously-caught
# UserAlreadyExistsError/InvalidCredentialsError/DatabaseError were dead code
# (never raised anywhere), so they have been removed rather than left to encode
# a contract that does not exist. Duplicate registration surfaces as a
# ValueError -> 400 with the (user-facing, non-sensitive) validation message.
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, req: Request):
    # Offload the rate limiter's blocking psycopg2 round-trip so it does not
    # stall the single uvicorn event loop; a raised HTTPException propagates back.
    await asyncio.to_thread(rate_limiter.check_rate_limit, req)
    # When the flag is off this block is skipped entirely and the endpoint
    # behaves exactly as it did before email verification existed — that is what
    # keeps the desktop/local profile and existing deploys working.
    if settings.EMAIL_VERIFICATION_ENABLED:
        if not request.code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先获取邮箱验证码")
        # Verified BEFORE the user row is inserted: the alternative (create
        # first, verify after) would leave a usable account behind whenever the
        # code turns out to be wrong. The cost is that a later failure in
        # register_user (e.g. duplicate username) burns the code and the user
        # has to request a new one.
        try:
            await asyncio.to_thread(
                email_verification.verify_code,
                request.email,
                email_verification.SCENE_REGISTER,
                request.code,
            )
        except email_verification.VerificationUnavailableError as e:
            # Feature switched on but `alembic upgrade main_db@head` never ran.
            logger.error(f"Registration unavailable: {_mask_email(request.email)}, error: {e}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
        except email_verification.VerificationError as e:
            logger.warning(f"Registration code rejected: {_mask_email(request.email)}, error: {e}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    try:
        result = await auth_service.register_user(
            username=request.username,
            email=request.email,
            password=request.password
        )
        logger.info(f"User registered: {_mask_email(request.email)}")
        return result
    except ValueError as e:
        # Registration ValueErrors are deliberate, user-facing validation
        # messages (password rules, "Email already registered", etc.).
        logger.warning(f"Registration validation error: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, req: Request):
    await asyncio.to_thread(rate_limiter.check_rate_limit, req)
    try:
        result = await auth_service.login_user(
            email=request.email,
            password=request.password,
        )
        logger.info(f"User logged in: {_mask_email(request.email)}")
        return result
    except ValueError as e:
        # Never echo the raw error text on the login path: it could reveal
        # internal detail and aids user-enumeration. Return a constant message.
        logger.warning(f"Login failed: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )


@router.get("/config")
async def auth_config():
    """Tell the SPA whether to render the verification-code field.

    No rate limit: this is a single boolean with no side effects, and the login
    page reads it on every load.
    """
    return {"email_verification_enabled": settings.EMAIL_VERIFICATION_ENABLED}


def _check_send_code_daily_cap(req: Request) -> None:
    """Per-IP daily cap on send-code. BLOCKING — call via ``asyncio.to_thread``.

    Backed by the same ``rate_limit_counters`` table as the per-minute limiter
    (see app/middleware/rate_limiter.py for the UPSERT-and-count idiom) so the
    cap survives a restart; an in-memory counter would reset every deploy.

    ``window_start`` holds the END of the day, not its start. RateLimiter's
    periodic sweep deletes rows whose ``window_start`` is older than two of its
    own 60s windows; a midnight-of-today value would be swept within minutes and
    the cap would never bind. Tomorrow-midnight stays in the future all day and
    is then collected by that same sweep — no extra cleanup needed, and no change
    to the limiter.

    Fails CLOSED: if the counter cannot be read we refuse to send rather than
    let an unmetered blast through.
    """
    client_id = f"send-code:{rate_limiter._get_client_id(req)}"
    day_end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    try:
        with get_db_session() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rate_limit_counters (client_id, window_start, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (client_id, window_start)
                DO UPDATE SET count = rate_limit_counters.count + 1
                RETURNING count
                """,
                (client_id, day_end),
            )
            row = cur.fetchone()
            # RealDictCursor returns a dict; a plain cursor returns a tuple.
            count = row["count"] if isinstance(row, dict) else row[0]
    except Exception:
        logger.error("send-code daily cap could not be recorded; refusing the send", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮件服务暂不可用，请稍后重试",
        )

    # Raised AFTER the block so the increment above is committed, not rolled back.
    if count > _SEND_CODE_DAILY_LIMIT:
        logger.warning("send-code daily cap reached for %s (%d requests)", client_id, count)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="今日验证码发送次数已达上限，请明天再试",
        )


async def _dispatch_code(email: str, scene: str) -> None:
    """Send a verification code, translating service errors into HTTP errors.

    Only the REGISTER scene uses this: that scene already reveals whether an
    address is taken, so reporting a cooldown or a delivery failure adds no
    enumeration surface. The reset scene must stay silent — see
    ``_dispatch_code_silently``.
    """
    try:
        await asyncio.to_thread(email_verification.send_code, email, scene)
    except email_verification.VerificationUnavailableError as e:
        # The table has not been migrated in. An operator problem, so say so
        # with a 503 instead of letting psycopg2's UndefinedTable become a 500.
        logger.error(f"Send-code unavailable: {_mask_email(email)}, scene: {scene}, error: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except email_verification.VerificationError as e:
        # send_code raises VerificationError for the resend cooldown and — as
        # implemented — also for a failed SMTP delivery, which it wraps rather
        # than letting MailerError escape. Both are "retry shortly" conditions
        # and the service's own Chinese message distinguishes them for the user,
        # so they share the 429. See the report note on this contract mismatch.
        logger.warning(f"Send-code refused: {_mask_email(email)}, scene: {scene}, error: {e}")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except mailer.MailerError:
        # Documented in the mailer contract; kept so a future send_code that
        # lets MailerError through still produces a sane status instead of a 500.
        logger.error(f"Verification email delivery failed: {_mask_email(email)}, scene: {scene}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="邮件发送失败，请稍后重试")


def _dispatch_code_silently(email: str, scene: str) -> None:
    """Send a code, swallowing every outcome. BLOCKING — runs as a BackgroundTask.

    Used by the RESET scene, where the send-side outcome must NEVER reach the
    client: a registered address that hits the 60s resend cooldown (or whose
    delivery fails) would otherwise answer 429 while an unregistered address
    always answers 200, which is a one-request user-enumeration oracle. Starlette
    runs a sync background function in a worker thread after the response has
    been sent, so nothing here can affect the status, body, or latency the caller
    observes.
    """
    try:
        email_verification.send_code(email, scene)
    except email_verification.VerificationError as e:
        # Expected: resend cooldown, or a delivery failure the service wrapped.
        logger.warning(f"Reset code not sent: {_mask_email(email)}, error: {e}")
    except (email_verification.VerificationUnavailableError, mailer.MailerError):
        logger.error(f"Reset code delivery failed: {_mask_email(email)}", exc_info=True)
    except Exception:
        # A background task has no caller to report to; an escaping exception
        # would be logged by starlette as an unhandled error and nothing else.
        logger.error(f"Reset code dispatch crashed: {_mask_email(email)}", exc_info=True)
    else:
        logger.info(f"Verification code sent: {_mask_email(email)}, scene: {scene}")


async def _hold_until_floor(started: float) -> None:
    remaining = _RESET_SEND_FLOOR_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


@router.post("/send-code")
async def send_code(request: SendCodeRequest, req: Request, background_tasks: BackgroundTasks):
    await asyncio.to_thread(rate_limiter.check_rate_limit, req)
    if not settings.EMAIL_VERIFICATION_ENABLED or not mailer.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮箱验证未启用，请联系管理员",
        )
    # Keyed on the client IP only, never on the address, so it cannot become an
    # enumeration signal on the reset path.
    await asyncio.to_thread(_check_send_code_daily_cap, req)

    started = time.monotonic()
    exists = await asyncio.to_thread(auth_service.email_exists, request.email)

    if request.scene == email_verification.SCENE_REGISTER:
        # Registration already tells the caller when an email is taken, so
        # reporting it here adds no enumeration surface — and it beats letting
        # the user spend a code only to have /register reject them.
        if exists:
            logger.warning(f"Send-code rejected, email already registered: {_mask_email(request.email)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已注册")
        await _dispatch_code(request.email, request.scene)
        logger.info(f"Verification code sent: {_mask_email(request.email)}, scene: {request.scene}")
        return {"sent": True}

    # scene == reset. An unknown address must be indistinguishable from a known
    # one, so both branches report {"sent": true}, both are held to the same
    # wall-clock pad, and NEITHER waits on (or reports) the delivery itself.
    if exists:
        background_tasks.add_task(_dispatch_code_silently, request.email, request.scene)
    else:
        logger.warning(f"Reset code requested for unknown email: {_mask_email(request.email)}")
    await _hold_until_floor(started)
    return {"sent": True}


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, req: Request):
    await asyncio.to_thread(rate_limiter.check_rate_limit, req)
    # Mirrors the send-code guard. Without it this route reaches verify_code ->
    # get_db_session unconditionally; on the frozen desktop build (PROFILE=local,
    # STORAGE_BACKEND=sqlite) psycopg2 is not bundled, so a POST to the loopback
    # port raised ImportError inside _get_main_pool and 500'd.
    if not settings.EMAIL_VERIFICATION_ENABLED or not mailer.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮箱验证未启用，请联系管理员",
        )
    try:
        await asyncio.to_thread(
            email_verification.verify_code,
            request.email,
            email_verification.SCENE_RESET,
            request.code,
        )
    except email_verification.VerificationUnavailableError as e:
        logger.error(f"Reset unavailable: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except email_verification.VerificationError as e:
        logger.warning(f"Reset code rejected: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        await auth_service.reset_password(email=request.email, new_password=request.new_password)
    except ValueError as e:
        # Same contract as register: reset_password raises plain ValueError only
        # for deliberate, user-facing messages.
        logger.warning(f"Password reset failed: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    logger.info(f"Password reset: {_mask_email(request.email)}")
    return {"reset": True}


@router.get("/shuake-token")
async def get_shuake_token(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    try:
        numeric_user_id = int(user_id)
    except (TypeError, ValueError):
        # A validly-signed but malformed/legacy token may carry a non-numeric
        # user_id; that is an authentication problem, not a server error.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    token = auth_service._create_shuake_token(numeric_user_id)
    if not token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Shuake token not configured")
    return {"shuake_token": token}
