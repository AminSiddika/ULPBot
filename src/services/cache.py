import json
from typing import Any

import redis.asyncio as aioredis

from src.config import settings

_redis: aioredis.Redis | None = None

DEFAULT_TTL = 600


async def connect_redis() -> aioredis.Redis:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call connect_redis() first.")
    return _redis


async def cache_get(key: str) -> Any | None:
    r = get_redis()
    data = await r.get(key)
    return json.loads(data) if data else None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    r = get_redis()
    await r.set(key, json.dumps(value), ex=ttl)


async def cache_delete(pattern: str) -> int:
    r = get_redis()
    keys = await r.keys(pattern)
    if keys:
        return await r.delete(*keys)
    return 0


async def check_rate_limit(user_id: int, limit: int = 10, window: int = 60) -> bool:
    r = get_redis()
    key = f"rate_limit:{user_id}"
    current = await r.incr(key)
    if current == 1:
        await r.expire(key, window)
    return current > limit
