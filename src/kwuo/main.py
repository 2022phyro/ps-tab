"""Kwuo application factory and root entrypoint."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from kwuo.core.config import settings
from kwuo.core.cache import get_redis_client
from kwuo.core.database import engine
from kwuo.models.base import Base

# Import web routes
from kwuo.web.routes.home import router as home_router
from kwuo.web.routes.auth import router as auth_router
from kwuo.web.routes.dashboard import router as dashboard_router
from kwuo.web.routes.admin import router as admin_router
from kwuo.web.routes.documentation import router as docs_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    # Ensure database tables exist (development convenience)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize Redis client
    redis = get_redis_client()
    yield
    # Cleanup on shutdown
    await redis.aclose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        description="Public Speaking Tabulation Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register web route modules
    app.include_router(home_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(admin_router)
    app.include_router(docs_router)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "app": settings.APP_NAME, "version": "0.1.0"}

    return app


app = create_app()
