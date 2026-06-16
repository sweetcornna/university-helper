import asyncio
import logging

from fastapi import APIRouter, HTTPException, status, Request, Depends
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import AuthService
from app.middleware.rate_limiter import rate_limiter
from app.dependencies import get_current_user

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)


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
