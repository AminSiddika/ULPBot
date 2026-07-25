import asyncio
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from src.config import settings
from src.utils.logger import logger

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_indexes_created: bool = False

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0


async def connect_db() -> AsyncIOMotorDatabase:
    global _client, _db
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _client = AsyncIOMotorClient(
                settings.mongo_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            _db = _client[settings.mongo_db]
            await _client.admin.command("ping")
            logger.info(f"MongoDB connected (attempt {attempt})")
            break
        except Exception as e:
            logger.warning(f"MongoDB connection attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
            else:
                raise

    await _ensure_indexes()
    return _db


async def _ensure_indexes() -> None:
    global _indexes_created
    if _indexes_created or _db is None:
        return
    await _db.users.create_index("user_id", unique=True)
    await _db.users.create_index("is_banned")
    await _db.usage_logs.create_index([("user_id", 1), ("created_at", -1)])
    await _db.usage_logs.create_index("created_at", expireAfterSeconds=30 * 86400)
    _indexes_created = True
    logger.info("MongoDB indexes ensured")


async def close_db() -> None:
    global _client, _indexes_created
    if _client:
        _client.close()
        _client = None
    _indexes_created = False


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _db


async def retry_mongo_op(op: Any, *args: Any, **kwargs: Any) -> Any:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await op(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Mongo op attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt >= MAX_RETRIES:
                raise
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
    return None
