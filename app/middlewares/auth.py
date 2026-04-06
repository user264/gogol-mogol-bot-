"""Middleware that loads user from DB and injects into handler data."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.database import async_session
from app.services.cook_service import get_user_by_tg, update_user_name


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_tg = None
        if isinstance(event, Update):
            if event.message:
                user_tg = event.message.from_user
            elif event.callback_query:
                user_tg = event.callback_query.from_user

        if user_tg:
            async with async_session() as session:
                db_user = await get_user_by_tg(session, user_tg.id)
                if db_user:
                    tg_name = user_tg.full_name or user_tg.username or str(user_tg.id)
                    await update_user_name(session, user_tg.id, tg_name)
                data["db_user"] = db_user
                data["session_factory"] = async_session

        return await handler(event, data)
