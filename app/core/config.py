"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-secret-key-change-me-in-production-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Manufacturing Production & Quality Control Management System"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | testing | production
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "sqlite:///./manufacturing.db"
    AUTO_CREATE_TABLES: bool = True  # dev convenience; production should use Alembic migrations

    # Security
    SECRET_KEY: str = _DEV_SECRET
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    BCRYPT_ROUNDS: int = 12
    CORS_ORIGINS: str = "*"  # comma separated

    # Bootstrap super admin (created on first start when no users exist)
    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "Admin@12345"
    FIRST_SUPERUSER_NAME: str = "System Administrator"

    # Rate limiting (in-memory sliding window; swap for Redis when running multiple workers)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 240
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # Business thresholds
    HIGH_REJECTION_THRESHOLD_PERCENT: float = 5.0
    HIGH_REJECTION_MIN_UNITS: int = 10
    DEADLINE_WARNING_DAYS: int = 2
    MAINTENANCE_DUE_WARNING_DAYS: int = 7

    # Shift timings are wall-clock times; timestamps are stored in UTC, so set the plant's UTC offset
    # (e.g. 330 for India) for shift detection to line up with local time.
    SHIFT_UTC_OFFSET_MINUTES: int = 0

    # Optional background checks (low stock, deadlines, maintenance due, ...)
    ENABLE_BACKGROUND_CHECKS: bool = False
    BACKGROUND_CHECK_INTERVAL_SECONDS: int = 300

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.is_production:
            if self.SECRET_KEY == _DEV_SECRET or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be set to a strong value (>=32 chars) in production")
            if self.AUTO_CREATE_TABLES:
                raise ValueError("Set AUTO_CREATE_TABLES=false in production and use Alembic migrations")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
