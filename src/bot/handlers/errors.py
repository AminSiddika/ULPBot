import sentry_sdk
from aiogram import Router, types

from src.config import settings
from src.utils.logger import logger

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
    )

router = Router()


@router.errors()
async def on_error(event: types.error_event.ErrorEvent) -> None:
    logger.exception(
        "Unhandled error in update {}",
        event.update.update_id if event.update else "unknown",
    )
    if settings.sentry_dsn:
        sentry_sdk.capture_exception(event.exception)
    if event.update.message:
        await event.update.message.answer(
            "❌ An internal error occurred. Please try again later.",
        )
