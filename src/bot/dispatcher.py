from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers import (
    admin,
    broadcast,
    combo,
    errors,
    extract,
    help,
    history,
    premium,
    start,
    ulp,
    validate,
)
from src.bot.middlewares.auth import AuthMiddleware, ThrottlingMiddleware

dp = Dispatcher(name="ULPBot")


def setup_dispatcher() -> Dispatcher:
    dp["default_bot_properties"] = DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        link_preview_is_disabled=True,
    )

    dp.update.outer_middleware(ThrottlingMiddleware(delay=0.3))
    dp.update.middleware(AuthMiddleware())

    dp.include_router(errors.router)
    dp.include_router(start.router)
    dp.include_router(help.router)
    dp.include_router(premium.router)
    dp.include_router(ulp.router)
    dp.include_router(extract.router)
    dp.include_router(combo.router)
    dp.include_router(history.router)
    dp.include_router(admin.router)
    dp.include_router(validate.router)
    dp.include_router(broadcast.router)

    return dp
