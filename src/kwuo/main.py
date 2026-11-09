"""Kwuo application factory and root entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from kwuo.core.config import settings
from kwuo.core.cache import get_redis_client
from kwuo.core.queue import close_arq_pool
from kwuo.core.database import engine, async_session_factory
from kwuo.core.rbac import seed_system_groups
from kwuo.models.base import Base

# Import web routes
from kwuo.web.routes.home import router as home_router
from kwuo.web.routes.auth import router as auth_router
from kwuo.web.routes.profile import router as profile_router
from kwuo.web.routes.dashboard import router as dashboard_router
from kwuo.web.routes.admin import router as admin_router
from kwuo.web.routes.documentation import router as docs_router
from kwuo.web.routes.tournaments import router as tournaments_router
from kwuo.web.routes.attachments import router as attachments_router
from kwuo.web.routes.tenant import router as tenant_router
from fastapi.middleware.gzip import GZipMiddleware
from kwuo.web.middleware.tenant import TenantSubdomainMiddleware
from kwuo.core.timing import PerformanceTimingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    # Ensure database tables exist (development convenience)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE tournaments ALTER COLUMN status TYPE VARCHAR(32);"))
        except Exception:
            pass

    # Seed pre-defined system security groups and permissions
    try:
        async with async_session_factory() as session:
            await seed_system_groups(session)
            await session.commit()
    except Exception as e:
        # Avoid blocking startup if DB is in migration
        pass

    # Initialize Redis client
    redis = get_redis_client()
    yield
    # Cleanup on shutdown
    try:
        await redis.aclose()
        await close_arq_pool()
    except Exception:
        pass


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
    app.include_router(profile_router)
    app.include_router(dashboard_router)
    app.include_router(tournaments_router)
    app.include_router(attachments_router)
    app.include_router(tenant_router)
    app.include_router(admin_router)
    app.include_router(docs_router)

    # Register compression and performance observation middlewares
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(PerformanceTimingMiddleware)
    app.add_middleware(TenantSubdomainMiddleware)

    # Mount static assets directory
    base_dir = Path(__file__).resolve().parent.parent.parent
    static_dir = base_dir / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "app": settings.APP_NAME, "version": "0.1.0"}

    return app


app = create_app()
