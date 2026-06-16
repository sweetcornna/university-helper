from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PUBLIC_ROUTES = [
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/chaoxing/location/geocode",
    "/api/v1/chaoxing/location/search",
    "/api/v1/chaoxing/location/reverse-geocode",
    "/docs",
    "/openapi.json",
    "/",
    "/health",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    MAIN_DB_HOST: str = "localhost"
    MAIN_DB_NAME: str = "main_db"
    MAIN_DB_USER: str
    MAIN_DB_PASSWORD: str
    MAIN_DB_PORT: int = 5432

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: list[str] = []

    # Security
    ENFORCE_HTTPS: bool = True
    BCRYPT_ROUNDS: int = 12

    # Environment ("dev", "production", …) drives several runtime guards.
    ENV: str = "dev"

    # Docs / Swagger UI — default off; opt in via env for local dev
    DOCS_ENABLED: bool = False

    BAIDU_MAP_API_KEY: str | None = None

    # Optional bearer token guarding the /metrics endpoint. When set, requests
    # to /metrics must present `Authorization: Bearer <METRICS_TOKEN>`. When
    # unset (default), /metrics is open — acceptable only because the documented
    # nginx topology does not proxy /metrics externally. Set this in any
    # deployment where the uvicorn container is otherwise reachable.
    METRICS_TOKEN: str | None = None

    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key_present(cls, v: str) -> str:
        if not v or len(v) < 16:
            raise ValueError("SECRET_KEY must be set and at least 16 chars")
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _cors_origins_present(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("CORS_ORIGINS must be set in environment variables")
        return v


settings = Settings()
