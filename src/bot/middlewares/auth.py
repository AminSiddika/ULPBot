from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, types
from aiogram.dispatcher.event.bases import CancelHandler

from src.config import settings
from src.database.repos.user import is_admin, is_banned, is_registered
from src.utils.logger import logger


PUBLIC_COMMANDS = {"start", "help", "cmds", "register", "redeem", "userinfo", "ping"}


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (types.Message, types.CallbackQuery)):
            return await handler(event, data)

        message: types.Message | None = getattr(event, "message", None) or event
        if not message or not message.from_user:
            return await handler(event, data)

        user_id = message.from_user.id
        data["is_owner"] = user_id == settings.owner_id
        data["is_admin"] = user_id in {settings.owner_id, *settings.admin_ids_set}

        if isinstance(event, types.Message) and event.text:
            command = event.text.strip().split()[0].lstrip("/").split("@")[0].lower()
            if command not in PUBLIC_COMMANDS:
                if event.from_user:
                    banned = await is_banned(event.from_user.id)
                    if banned:
                        await event.answer("🚫 You are banned from this bot.")
                        raise CancelHandler()

                    registered = await is_registered(event.from_user.id)
                    if not registered:
                        await event.answer(
                            "⚠️ <b>Registration Required</b>\n\n"
                            "Please /register first to use the bot.\n"
                            "Registration gives you 10 free searches.",
                        )
                        raise CancelHandler()

        return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, delay: float = 0.3):
        self._delay = delay
        self._last_call: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        import time

        if isinstance(event, types.Message) and event.from_user:
            user_id = event.from_user.id
            now = time.monotonic()
            if user_id in self._last_call and now - self._last_call[user_id] < self._delay:
                raise CancelHandler()
            self._last_call[user_id] = now

        return await handler(event, data)
