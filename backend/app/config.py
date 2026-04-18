"""
Application configuration loaded from environment variables.

All secrets and tunables are read from env vars (populated via .env file
in development, injected by Docker in production).

Returns:
    Settings: A pydantic BaseSettings singleton used across the app.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration – every field maps to an env var."""

    # ── App ───────────────────────────────────────────────
    APP_NAME: str = "YoutubeFilterAi"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: str = "http://localhost:5173"  # comma-separated

    # ── Database ──────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://ytfilter:ytfilter@db:5432/ytfilter"

    # ── Redis ─────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Auth ──────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALLOW_GMAIL_AUTH: bool = False
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # ── Admin ─────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change-me"

    # ── OpenRouter AI ─────────────────────────────────────
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Per-user token; free-tier rate-limit defaults (requests per minute)
    OPENROUTER_FREE_RPM: int = 10

    # ── Telegram ──────────────────────────────────────────
    # Users create their own bots; no global token needed.
    # Optional: real token for integration tests.
    TEST_TELEGRAM_BOT_TOKEN: str = ""
    TEST_TELEGRAM_CHAT_ID: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Uses ``@lru_cache`` to ensure environment variables are read only once.
    Call ``get_settings.cache_clear()`` to force re-read (e.g. in tests).

    Returns:
        Settings: Pydantic settings instance with all configuration values.
    """
    return Settings()
