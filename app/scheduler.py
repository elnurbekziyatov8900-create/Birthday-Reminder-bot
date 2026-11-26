from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.messaging import GroupTarget, get_active_groups, send_birthday_greeting
from app.models import NotificationLog
from app.services import PersonData, birthdays_today


settings = get_settings()
logger = logging.getLogger(__name__)

# Muvaffaqiyatsiz yuborishni bir kunda necha marta va qanday oraliqda
# qayta urinish. Avval xato bo'lsa bot har daqiqada qayta urinardi.
MAX_ATTEMPTS_PER_DAY = 5
RETRY_INTERVAL = timedelta(minutes=10)


def _parse_reminder_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = map(int, value.split(":"))
    except (ValueError, AttributeError):
        raise ValueError(f"Noto'g'ri reminder_time: {value}") from None

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"Noto'g'ri reminder_time: {value}")

    return hour, minute


def _get_group_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Noto'g'ri timezone: {value}") from None


def _normalize(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value


async def _get_log(
    session,
    person_id: int,
    birthday_year: int,
    chat_id: int,
) -> NotificationLog | None:
    return await session.scalar(
        select(NotificationLog).where(
            NotificationLog.person_id == person_id,
            NotificationLog.birthday_year == birthday_year,
            NotificationLog.chat_id == chat_id,
        )
    )


def _should_attempt(log_entry: NotificationLog | None, now: datetime) -> bool:
    if log_entry is None:
        return True

    if log_entry.status == "sent":
        return False

    if (log_entry.attempts or 0) >= MAX_ATTEMPTS_PER_DAY:
        return False

    last_attempt = _normalize(log_entry.last_attempt_at)

    return last_attempt is None or now - last_attempt >= RETRY_INTERVAL


async def _process_group(bot: Bot, group: GroupTarget) -> None:
    chat_id = group.chat_id

    try:
        group_timezone = _get_group_timezone(group.timezone)
        hour, minute = _parse_reminder_time(group.reminder_time)
    except ValueError:
        logger.exception("Guruh sozlamalari noto'g'ri: chat_id=%s", chat_id)
        return

    now_local = datetime.now(group_timezone)

    if (now_local.hour, now_local.minute) < (hour, minute):
        return

    today = now_local.date()
    now_utc = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        # ORM obyektlaridan nusxa olamiz: keyingi commit'lar ularni
        # "expire" qiladi va async rejimda lazy-load xatosi chiqardi.
        people = [
            PersonData.from_person(person)
            for person in await birthdays_today(session, today, group.id)
        ]

    if not people:
        return

    for person in people:
        try:
            async with SessionLocal() as session:
                log_entry = await _get_log(session, person.id, today.year, chat_id)

                if not _should_attempt(log_entry, now_utc):
                    continue

                logger.info(
                    "Tabrik yuborilmoqda: person_id=%s, chat_id=%s, date=%s",
                    person.id,
                    chat_id,
                    today,
                )

                result = await send_birthday_greeting(bot, chat_id, person, today)

                # Guruh superguruhga ko'chgan bo'lsa, yangi ID bo'yicha yozamiz.
                if result.chat_id != chat_id:
                    chat_id = result.chat_id
                    log_entry = await _get_log(
                        session, person.id, today.year, chat_id
                    )

                if log_entry is None:
                    log_entry = NotificationLog(
                        person_id=person.id,
                        birthday_year=today.year,
                        chat_id=chat_id,
                        attempts=0,
                    )
                    session.add(log_entry)

                log_entry.attempts = (log_entry.attempts or 0) + 1
                log_entry.last_attempt_at = now_utc

                if result.greeting_sent:
                    log_entry.status = "sent"
                    log_entry.sent_at = now_utc
                    log_entry.telegram_message_id = result.message_id
                    log_entry.error_message = result.music_error
                    logger.info(
                        "Tabrik yuborildi: person_id=%s, chat_id=%s",
                        person.id,
                        chat_id,
                    )
                else:
                    log_entry.status = "failed"
                    log_entry.error_message = result.error

                await session.commit()

        except Exception:
            logger.exception(
                "Tabrikni qayta ishlashda xatolik: person_id=%s, chat_id=%s",
                person.id,
                chat_id,
            )


async def send_daily_birthdays(bot: Bot) -> None:
    async with SessionLocal() as session:
        groups = await get_active_groups(session)

    if not groups:
        logger.debug("Faol eslatma guruhlari topilmadi.")
        return

    for group in groups:
        await _process_group(bot, group)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=_get_group_timezone(settings.timezone))

    # Har daqiqada tekshiriladi: har bir guruhning o'z eslatma vaqti va
    # vaqt zonasi bo'lishi mumkin. Takroriy yuborishdan NotificationLog
    # himoya qiladi.
    scheduler.add_job(
        send_daily_birthdays,
        trigger="cron",
        second=0,
        args=[bot],
        id="daily_birthdays",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    logger.info(
        "Scheduler sozlandi: har daqiqada tekshiruv, timezone=%s",
        settings.timezone,
    )

    return scheduler
