"""Pytest configuration and test database fixtures."""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import os
from kwuo.core.config import settings

# Force testing environment for unit/integration tests
os.environ["ENVIRONMENT"] = "testing"
settings.ENVIRONMENT = "testing"

from kwuo.main import app
from kwuo.models.base import Base
import kwuo.models  # Ensure all model tables are registered on Base.metadata
from kwuo.core.database import get_db_session

# In-memory async SQLite engine for lightning-fast testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Bind kwuo.core.database session factory to in-memory test DB
import kwuo.core.database
kwuo.core.database.async_session_factory = TestSessionLocal
kwuo.core.database.engine = test_engine


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create fresh database tables for each test and yield session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test HTTP client with overridden database dependency."""
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
