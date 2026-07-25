import json
from typing import Any

import redis.asyncio as aioredis

from src.config import settings
from src.utils.logger import logger

_redis: aioredis.Redis | None = None
_available: bool = False

DEFAULT_TTL = 600


async def connect_redis() -> aioredis.Redis | None:
    global _redis, _available
    try:
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await _redis.ping()
        _available = True
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}) — running without caching")
        _available = False
        _redis = None
    return _redis


async def close_redis() -> None:
    global _redis, _available
    if _redis:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None
    _available = False


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not available.")
    return _redis


async def cache_get(key: str) -> Any | None:
    if not _available or _redis is None:
        return None
    try:
        data = await _redis.get(key)
        return json.loads(data) if data else None
    except Exception:
        _available = False
        return None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    if not _available or _redis is None:
        return
    try:
        await _redis.set(key, json.dumps(value), ex=ttl)
    except Exception:
        _available = False


async def cache_delete(pattern: str) -> int:
    if not _available or _redis is None:
        return 0
    try:
        keys = await _redis.keys(pattern)
        if keys:
            return await _redis.delete(*keys)
    except Exception:
        _available = False
    return 0
