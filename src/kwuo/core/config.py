"""Application settings and environment configuration for Kwuo."""

import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Kwuo"
    ENVIRONMENT: str = Field(
        default="development",
        description="Application environment runtime: development, staging, production, testing",
    )
    DEBUG: bool = False

    # Security: Cryptographic secret key for signing JWTs and session cookies.
    # Must be supplied via environment variable (SECRET_KEY) or .env file.
    SECRET_KEY: str = Field(
        default="",
        description="Cryptographic secret key for signing JWTs and session cookies. Must be provided in environment.",
    )

    # Database: PostgreSQL via asyncpg
    # Connection URL with credentials must be supplied via environment variable (DATABASE_URL) or .env file.
    DATABASE_URL: str = Field(
        default="",
        description="Async PostgreSQL connection URL with credentials. Must be provided in environment.",
    )

    # Redis (cache and ARQ queue)
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching and ARQ queues.",
    )

    # Server Host & Port
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    @field_validator("SECRET_KEY", mode="after")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if not v:
            env = os.getenv("ENVIRONMENT", "development").lower()
            if env in ("production", "prod"):
                raise ValueError("SECRET_KEY environment variable is required in production and must not be empty.")
            # For development / testing fallback without an explicit secret key
            return "kwuo-dev-secret-key-must-be-set-in-env-for-production-min32b"
        if len(v) < 32 and os.getenv("ENVIRONMENT", "").lower() in ("production", "prod"):
            raise ValueError("SECRET_KEY must be at least 32 characters long in production.")
        return v

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            env = os.getenv("ENVIRONMENT", "development").lower()
            if env in ("production", "prod"):
                raise ValueError("DATABASE_URL environment variable is required in production and must not be empty.")
            # Default development fallback pointing to local postgres without hardcoded passwords
            return "postgresql+asyncpg://localhost:5432/kwuo"
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
