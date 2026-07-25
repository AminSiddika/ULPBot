from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, generate_latest

from src.bot.dispatcher import dp
from src.config import settings
from src.utils.logger import logger

search_requests = Counter("ulp_search_total", "Total search requests", ["command"])
search_results = Counter("ulp_results_total", "Total results returned", ["command"])
active_users = Gauge("ulp_active_users", "Currently active users (last 5 min)")

METRICS_UPDATE_INTERVAL = 300


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot = app.state.bot
    webhook_url = settings.webhook_url
    await bot.set_webhook(
        webhook_url,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    logger.info(f"Webhook set to {webhook_url}")
    yield
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook removed")


async def create_webhook_app(bot: Bot) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.bot = bot

    @app.get("/health")
    async def health():
        return {"status": "ok", "bot": (await bot.get_me()).username}

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse(generate_latest(), media_type="text/plain")

    @app.post(settings.webhook_path)
    async def webhook(request: Request):
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_webhook_update(bot, update)
        return {"ok": True}

    return app
