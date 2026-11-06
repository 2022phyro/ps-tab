"""ARQ background queue connection and job dispatch manager for Kwuo."""

import logging
from typing import Any, Optional
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from kwuo.core.config import settings

logger = logging.getLogger("kwuo.queue")

_arq_pool: Optional[ArqRedis] = None


async def get_arq_pool() -> Optional[ArqRedis]:
    """Retrieve or initialize the global ARQ Redis connection pool."""
    global _arq_pool
    if _arq_pool is None:
        try:
            _arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        except Exception as e:
            logger.debug(f"ARQ Redis pool not available at {settings.REDIS_URL}: {e}")
            return None
    return _arq_pool


async def close_arq_pool() -> None:
    """Close the ARQ Redis connection pool."""
    global _arq_pool
    if _arq_pool is not None:
        try:
            await _arq_pool.close()
        except Exception:
            pass
        _arq_pool = None


async def enqueue_job(function_name: str, *args: Any, **kwargs: Any) -> bool:
    """Enqueue a job to the ARQ Redis queue.
    
    Returns True if successfully pushed to the queue.
    Returns False if in testing environment or if Redis/ARQ is unavailable.
    """
    if settings.ENVIRONMENT == "testing":
        return False

    pool = await get_arq_pool()
    if pool is not None:
        try:
            job = await pool.enqueue_job(function_name, *args, **kwargs)
            return job is not None
        except Exception as e:
            logger.warning(f"Failed to enqueue {function_name} to ARQ: {e}")
            return False
    return False
