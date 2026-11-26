"""Telegramga xabar yuborish uchun umumiy yordamchilar.

Scheduler ham, /testbirthday komandasi ham shu modul orqali tabrik
yuboradi — shu sababli ikkalasining natijasi bir xil ko'rinadi.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from html import unescape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramMigrateToChat,
    TelegramRetryAfter,
)
from aiogram.types import ReplyParameters
from sqlalchemy import select, update

from app.config import get_settings
from app.database import SessionLocal
from app.models import GroupConfig, NotificationLog, Person
from app.services import (
    PersonData,
    make_greeting,
    make_greeting_caption,
    music_caption,
)


logger = logging.getLogger(__name__)
settings = get_settings()

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
SAFE_TEXT_LIMIT = 4000
MAX_RETRY_AFTER_SECONDS = 60


# ================================================================
# MATNNI BO'LAKLARGA AJRATISH
# ================================================================

_TAG_RE = re.compile(r"<[^>]+>")


def telegram_length(html_text: str) -> int:
    """HTML teglarsiz matn uzunligi (Telegram UTF-16 birliklarida sanaydi).

    Telegram limiti (caption: 1024, xabar: 4096) teglar emas, balki
    foydalanuvchi ko'radigan matnga qo'llanadi.
    """

    visible = unescape(_TAG_RE.sub("", html_text))
    return len(visible.encode("utf-16-le")) // 2


def split_html_text(text: str, limit: int = SAFE_TEXT_LIMIT) -> list[str]:
    """Uzun HTML matnni Telegram limitiga mos bo'laklarga ajratadi.

    Avval paragraflar (``\\n\\n``) bo'yicha, keyin qatorlar bo'yicha
    bo'linadi — shu tariqa ``<blockquote>`` kabi ko'p qatorli teglar
    o'rtasidan kesilmaydi.
    """

    text = text.strip()

    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(paragraph) > limit:
            split_at = paragraph.rfind("\n", 0, limit)

            if split_at < limit // 2:
                split_at = paragraph.rfind(" ", 0, limit)

            if split_at < limit // 2:
                split_at = limit

            chunks.append(paragraph[:split_at].strip())
            paragraph = paragraph[split_at:].strip()

        current = paragraph

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]


# ================================================================
# FAOL GURUHLAR
# ================================================================

@dataclass(frozen=True, slots=True)
class GroupTarget:
    id: int | None
    chat_id: int
    title: str
    timezone: str
    reminder_time: str


async def get_active_groups(session) -> list[GroupTarget]:
    """Bazadagi faol guruhlar (har birining o'z oila jadvali bor).

    ``.env`` dagi ``TARGET_GROUP_ID`` faqat bazada birorta ham guruh
    bo'lmaganda birinchi guruh sifatida qo'shiladi (``init_db``).
    """

    result = await session.scalars(
        select(GroupConfig)
        .where(GroupConfig.is_active.is_(True))
        .order_by(GroupConfig.id.asc())
    )

    groups = [
        GroupTarget(
            id=config.id,
            chat_id=config.chat_id,
            title=config.title,
            timezone=config.timezone,
            reminder_time=config.reminder_time,
        )
        for config in result.all()
    ]

    return groups


# ================================================================
# GURUH ID MIGRATSIYASI
# ================================================================

async def migrate_group_chat_id(old_chat_id: int, new_chat_id: int) -> None:
    """Guruh superguruhga aylanganda bazadagi chat ID'ni yangilaydi."""

    async with SessionLocal() as session:
        existing_new = await session.scalar(
            select(GroupConfig).where(GroupConfig.chat_id == new_chat_id)
        )

        old_config = await session.scalar(
            select(GroupConfig).where(GroupConfig.chat_id == old_chat_id)
        )

        if existing_new is not None and old_config is not None:
            # Ikkala yozuv ham bor: insonlarni yangi guruhga ko'chirib,
            # eski yozuvni o'chiramiz.
            existing_new.is_active = True
            await session.execute(
                update(Person)
                .where(Person.group_id == old_config.id)
                .values(group_id=existing_new.id)
            )
            await session.delete(old_config)
        else:
            await session.execute(
                update(GroupConfig)
                .where(GroupConfig.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
            )

        await session.execute(
            update(NotificationLog)
            .where(NotificationLog.chat_id == old_chat_id)
            .values(chat_id=new_chat_id)
        )

        await session.commit()

    logger.warning(
        "Guruh ID yangilandi (superguruhga migratsiya): %s -> %s",
        old_chat_id,
        new_chat_id,
    )

    if settings.target_group_id == old_chat_id:
        logger.warning(
            ".env dagi TARGET_GROUP_ID eskirgan. Uni %s ga almashtiring.",
            new_chat_id,
        )


async def _call(coro_factory, chat_id: int):
    """Telegram so'rovini RetryAfter va MigrateToChat holatlarida qayta urinadi."""

    current_chat_id = chat_id

    for _ in range(3):
        try:
            return await coro_factory(current_chat_id), current_chat_id

        except TelegramRetryAfter as error:
            wait = min(int(error.retry_after) + 1, MAX_RETRY_AFTER_SECONDS)
            logger.warning(
                "Telegram limiti: %s soniya kutilmoqda (chat_id=%s)",
                wait,
                current_chat_id,
            )
            await asyncio.sleep(wait)

        except TelegramMigrateToChat as error:
            new_chat_id = int(error.migrate_to_chat_id)
            await migrate_group_chat_id(current_chat_id, new_chat_id)
            current_chat_id = new_chat_id

    return await coro_factory(current_chat_id), current_chat_id


# ================================================================
# TABRIK YUBORISH
# ================================================================

@dataclass(slots=True)
class DeliveryResult:
    chat_id: int
    greeting_sent: bool = False
    music_sent: bool = False
    message_id: int | None = None
    error: str | None = None
    music_error: str | None = None
    extra_message_ids: list[int] = field(default_factory=list)


async def send_text(bot: Bot, chat_id: int, text: str) -> tuple[list[int], int]:
    message_ids: list[int] = []

    for chunk in split_html_text(text):
        sent, chat_id = await _call(
            lambda cid, chunk=chunk: bot.send_message(
                chat_id=cid,
                text=chunk,
                parse_mode="HTML",
                disable_web_page_preview=True,
            ),
            chat_id,
        )
        message_ids.append(sent.message_id)

    return message_ids, chat_id


async def send_birthday_greeting(
    bot: Bot,
    chat_id: int,
    person: PersonData,
    today: date,
) -> DeliveryResult:
    """Tabrikni (surat + matn + musiqa) guruhga yuboradi.

    Xatolik bo'lsa istisno ko'tarmaydi — natija ``DeliveryResult`` ichida.
    """

    result = DeliveryResult(chat_id=chat_id)
    greeting = make_greeting(person, today)

    try:
        if person.photo_file_id:
            # Surat va to'liq tabrik BITTA xabarda: tabrik surat ostiga
            # (caption) joylanadi. Limitdan oshsa, to'rtliksiz ixcham variant,
            # u ham sig'masa — qisqa sarlavha + alohida matn.
            caption = greeting

            if telegram_length(caption) > TELEGRAM_CAPTION_LIMIT:
                caption = make_greeting(person, today, compact=True)

            fits = telegram_length(caption) <= TELEGRAM_CAPTION_LIMIT

            if not fits:
                caption = make_greeting_caption(person, today)

            sent, chat_id = await _call(
                lambda cid: bot.send_photo(
                    chat_id=cid,
                    photo=person.photo_file_id,
                    caption=caption,
                    parse_mode="HTML",
                ),
                chat_id,
            )
            result.message_id = sent.message_id

            if not fits:
                ids, chat_id = await send_text(bot, chat_id, greeting)
                result.extra_message_ids.extend(ids)

        else:
            ids, chat_id = await send_text(bot, chat_id, greeting)
            result.message_id = ids[0] if ids else None
            result.extra_message_ids.extend(ids[1:])

        result.greeting_sent = True

    except TelegramAPIError as error:
        result.error = str(error)[:1000]
        logger.error(
            "Tabrik yuborilmadi: person_id=%s, chat_id=%s, error=%s",
            person.id,
            chat_id,
            error,
        )
        result.chat_id = chat_id
        return result

    except Exception as error:  # noqa: BLE001 - natijani foydalanuvchiga qaytaramiz
        result.error = str(error)[:1000]
        logger.exception(
            "Tabrik yuborishda kutilmagan xatolik: person_id=%s, chat_id=%s",
            person.id,
            chat_id,
        )
        result.chat_id = chat_id
        return result

    result.chat_id = chat_id

    if person.music_file_id:
        # Telegram bitta xabarda ham surat, ham audio bo'lishiga ruxsat
        # bermaydi, shuning uchun qo'shiq tabrikka "javob" sifatida
        # yuboriladi — chatda ular bir-biriga bog'langan holda ko'rinadi.
        reply_to = (
            ReplyParameters(
                message_id=result.message_id,
                allow_sending_without_reply=True,
            )
            if result.message_id
            else None
        )

        try:
            await _call(
                lambda cid: bot.send_audio(
                    chat_id=cid,
                    audio=person.music_file_id,
                    caption=music_caption(person.full_name),
                    parse_mode="HTML",
                    reply_parameters=reply_to,
                ),
                chat_id,
            )
            result.music_sent = True

        except Exception as error:  # noqa: BLE001
            result.music_error = str(error)[:1000]
            logger.exception(
                "Musiqa yuborilmadi: person_id=%s, chat_id=%s",
                person.id,
                chat_id,
            )

    return result
