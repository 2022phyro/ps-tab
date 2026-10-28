"""Redis client and MessagePack-backed cache layer for Kwuo."""

from typing import Any, Optional
import redis.asyncio as aioredis
from kwuo.core.config import settings
from kwuo.core.msgpack import packb, unpackb

redis_client: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    """Get or initialize the global async Redis client."""
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    return redis_client


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Store a Python object in Redis packed as MessagePack."""
    client = get_redis_client()
    packed = packb(value)
    await client.set(key, packed, ex=ttl_seconds)


async def cache_get(key: str) -> Optional[Any]:
    """Retrieve and unpack a MessagePack-encoded object from Redis."""
    client = get_redis_client()
    data = await client.get(key)
    if data is None:
        return None
    return unpackb(data)


async def cache_delete(key: str) -> None:
    """Remove a key from Redis."""
    client = get_redis_client()
    await client.delete(key)
