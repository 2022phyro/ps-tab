"""ARQ background worker tasks and settings for Kwuo."""

from typing import Any, Dict
from arq.connections import RedisSettings
from kwuo.core.config import settings


async def startup(ctx: Dict[Any, Any]) -> None:
    """Worker startup hook."""
    pass


async def shutdown(ctx: Dict[Any, Any]) -> None:
    """Worker shutdown hook."""
    pass


class WorkerSettings:
    """ARQ Worker configuration."""
    functions = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
