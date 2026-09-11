import redis.asyncio as redis
from typing import AsyncIterator

REDIS_URL = "redis://localhost:6379/0"

redis_client: redis.Redis | None = None

async def init_redis() -> None:
    """Initializes the Redis connection pool."""
    global redis_client
    redis_client = redis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )

async def close_redis() -> None:
    """Closes the Redis connection pool."""
    global redis_client
    if redis_client:
        await redis_client.aclose()

async def get_redis() -> AsyncIterator[redis.Redis]:
    """Dependency injector yielding the Redis client to route handlers."""
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized.")
    yield redis_client