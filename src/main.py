import asyncio
import signal

import uvicorn
from aiogram import Bot

from src.bot.dispatcher import dp, setup_dispatcher
from src.config import settings
from src.database.engine import close_db, connect_db
from src.services.cache import close_redis, connect_redis
from src.services.scheduler import setup_scheduler
from src.utils.logger import logger
from src.webhook import create_webhook_app


async def on_startup(bot: Bot) -> None:
    logger.info("Connecting to MongoDB...")
    await connect_db()
    logger.info("Connecting to Redis...")
    await connect_redis()

    from src.database.engine import get_db
    db = get_db()
    await db.users.create_index("user_id", unique=True)
    await db.usage_logs.create_index("user_id")
    await db.usage_logs.create_index("created_at")

    setup_scheduler()

    me = await bot.get_me()
    logger.info(f"Bot @{me.username} is ready")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down...")
    from src.services.scheduler import scheduler
    scheduler.shutdown(wait=False)
    await close_redis()
    await close_db()
    await bot.session.close()
    logger.info("Shutdown complete")


async def run_polling(bot: Bot) -> None:
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    setup_dispatcher()
    logger.info("Starting polling...")
    await dp.start_polling(bot)


async def run_webhook(bot: Bot) -> None:
    setup_dispatcher()

    await on_startup(bot)
    app = await create_webhook_app(bot)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async def shutdown():
        server.should_exit = True
        await on_shutdown(bot)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    logger.info(f"Starting webhook on port {settings.webhook_port}...")
    await server.serve()


async def main() -> None:
    bot = Bot(token=settings.bot_token)

    if settings.use_webhook:
        await run_webhook(bot)
    else:
        await run_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
