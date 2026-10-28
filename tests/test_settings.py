"""Tests for application settings and environment configuration."""

import pytest
from pydantic import ValidationError
from kwuo.core.config import Settings


def test_settings_development_defaults(monkeypatch):
    """Verify safe development fallback behavior when environment variables are omitted."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")

    test_settings = Settings(_env_file=None)
    assert test_settings.ENVIRONMENT == "development"
    assert "dev-secret-key" in test_settings.SECRET_KEY or len(test_settings.SECRET_KEY) >= 32
    assert "postgresql+asyncpg://" in test_settings.DATABASE_URL
    assert "ps_tab_password" not in test_settings.DATABASE_URL


def test_settings_production_requires_secret_key(monkeypatch):
    """Verify that production runtime strictly rejects empty SECRET_KEY."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://prod_user:secret@prod-db:5432/kwuo")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    assert "SECRET_KEY environment variable is required in production" in str(excinfo.value)


def test_settings_production_rejects_short_secret_key(monkeypatch):
    """Verify that production runtime rejects short/insecure SECRET_KEY (<32 chars)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "too-short-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://prod_user:secret@prod-db:5432/kwuo")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    assert "SECRET_KEY must be at least 32 characters long in production" in str(excinfo.value)


def test_settings_production_requires_database_url(monkeypatch):
    """Verify that production runtime strictly rejects empty DATABASE_URL."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    assert "DATABASE_URL environment variable is required in production" in str(excinfo.value)


def test_settings_valid_custom_environment(monkeypatch):
    """Verify settings correctly load custom environment variables."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "super-secure-production-key-that-is-long-enough-32char")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://custom_user:custom_pass@prod-host:5432/custom_db")
    monkeypatch.setenv("REDIS_URL", "redis://custom-redis:6379/1")

    custom_settings = Settings(_env_file=None)
    assert custom_settings.SECRET_KEY == "super-secure-production-key-that-is-long-enough-32char"
    assert custom_settings.DATABASE_URL == "postgresql+asyncpg://custom_user:custom_pass@prod-host:5432/custom_db"
    assert custom_settings.REDIS_URL == "redis://custom-redis:6379/1"
