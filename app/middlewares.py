"""Bot tezligini kuzatish uchun middleware'lar.

Har bir kelgan xabar/tugma qancha vaqtda qayta ishlanganini va Telegram
API'ga qilingan sekin so'rovlarni logga yozadi. Shaxsiy ma'lumot (masalan,
parol) logga tushmasligi uchun xabar matni yozilmaydi — faqat komanda nomi.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response, TelegramType
from aiogram.types import TelegramObject, Update


logger = logging.getLogger("app.timing")

# Shundan uzoq davom etgan update/so'rov WARNING sifatida yoziladi.
SLOW_UPDATE_MS = 1500
SLOW_REQUEST_MS = 1000


def describe_update(update: Update) -> str:
    """Update'ning qisqa, maxfiy ma'lumotsiz tavsifi."""

    if update.message is not None:
        message = update.message
        text = message.text or message.caption or ""

        if text.startswith("/"):
            kind = text.split()[0].split("@")[0]
        elif message.photo:
            kind = "photo"
        elif message.audio or message.document:
            kind = "file"
        elif text:
            kind = "text"
        else:
            kind = message.content_type

        return f"{kind} ({message.chat.type})"

    if update.callback_query is not None:
        data = (update.callback_query.data or "").split(":")[0]
        return f"callback:{data}"

    return update.event_type


class UpdateTimingMiddleware(BaseMiddleware):
    """Har bir update qayta ishlanish vaqtini logga yozadi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = time.perf_counter()

        try:
            return await handler(event, data)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            label = describe_update(event) if isinstance(event, Update) else type(event).__name__
            level = logging.WARNING if elapsed_ms >= SLOW_UPDATE_MS else logging.INFO
            logger.log(level, "%s — %.0f ms%s", label, elapsed_ms,
                       "  (SEKIN)" if level == logging.WARNING else "")


class SlowRequestMiddleware(BaseRequestMiddleware):
    """Telegram API'ga sekin javob bergan so'rovlarni logga yozadi."""

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        started = time.perf_counter()

        try:
            return await make_request(bot, method)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000

            # getUpdates — long polling, u ataylab uzoq kutadi.
            if elapsed_ms >= SLOW_REQUEST_MS and method.__api_method__ != "getUpdates":
                logger.warning(
                    "Telegram API sekin: %s — %.0f ms",
                    method.__api_method__,
                    elapsed_ms,
                )
