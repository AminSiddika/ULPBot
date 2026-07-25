import asyncio
import os
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database.engine import get_db
from src.database.repos.log import get_stats
from src.services.cache import cache_delete
from src.utils.logger import logger

scheduler = AsyncIOScheduler()


async def _clean_downloads() -> None:
    dl_path = Path(settings.downloads_dir)
    count = 0
    for fp in dl_path.iterdir():
        if fp.is_file():
            fp.unlink()
            count += 1
    if count:
        logger.info(f"Scheduler: cleaned {count} download files")


async def _aggregate_daily_stats() -> None:
    try:
        stats = await get_stats()
        logger.info(
            f"Daily stats — Users: {stats['total_users']}, "
            f"Queries: {stats['total_queries']}"
        )
        db = get_db()
        await db.daily_stats.insert_one(stats)
    except Exception as e:
        logger.error(f"Failed to aggregate daily stats: {e}")


async def _flush_old_cache() -> None:
    try:
        deleted = await cache_delete("search:*")
        if deleted:
            logger.info(f"Scheduler: flushed {deleted} cached search entries")
    except Exception as e:
        logger.error(f"Failed to flush cache: {e}")


def setup_scheduler() -> None:
    scheduler.add_job(_clean_downloads, "interval", hours=1, id="clean_downloads")
    scheduler.add_job(_aggregate_daily_stats, "cron", hour=0, minute=0, id="daily_stats")
    scheduler.add_job(_flush_old_cache, "interval", hours=6, id="flush_cache")
    scheduler.start()
    logger.info("Scheduler started (cleanup every 1h, stats daily, cache flush every 6h)")
