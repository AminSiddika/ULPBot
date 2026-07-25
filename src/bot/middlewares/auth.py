from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, types
from aiogram.dispatcher.event.bases import CancelHandler

from src.config import settings
from src.database.repos.user import is_admin


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
