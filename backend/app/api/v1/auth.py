from fastapi import APIRouter, HTTPException, status, Request, Depends
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import AuthService
from app.middleware.rate_limiter import rate_limiter
from app.core.exceptions import UserAlreadyExistsError, InvalidCredentialsError, DatabaseError
from app.dependencies import get_current_user
import logging

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)


def _mask_email(email: str) -> str:
    """Mask email for safe logging: user@example.com -> u***@example.com"""
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[0]}***@{domain}" if local else f"***@{domain}"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, req: Request):
    rate_limiter.check_rate_limit(req)
    try:
        result = await auth_service.register_user(
            username=request.username,
            email=request.email,
            password=request.password
        )
        logger.info(f"User registered: {_mask_email(request.email)}")
        return result
    except UserAlreadyExistsError:
        logger.warning(f"Registration failed - user exists: {_mask_email(request.email)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
    except ValueError as e:
        logger.warning(f"Registration validation error: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except DatabaseError as e:
        logger.error(f"Database error during registration: {_mask_email(request.email)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error")


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, req: Request):
    rate_limiter.check_rate_limit(req)
    try:
        result = await auth_service.login_user(
            email=request.email,
            password=request.password,
        )
        logger.info(f"User logged in: {_mask_email(request.email)}")
        return result
    except InvalidCredentialsError:
        logger.warning(f"Login failed - invalid credentials: {_mask_email(request.email)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except ValueError as e:
        logger.warning(f"Login validation/credential error: {_mask_email(request.email)}, error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except DatabaseError as e:
        logger.error(f"Database error during login: {_mask_email(request.email)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error")


@router.get("/shuake-token")
async def get_shuake_token(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    token = auth_service._create_shuake_token(int(user_id))
    if not token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Shuake token not configured")
    return {"shuake_token": token}
