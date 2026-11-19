import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import NotificationLog, GroupConfig
from app.services import (
    local_today,
    birthdays_today,
    make_greeting,
    already_notified,
)


settings = get_settings()
logger = logging.getLogger(__name__)


# ============================================================
# PREMIUM CUSTOM EMOJI
# ============================================================

PREMIUM_PARTY_EMOJI = (
    '<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji>'
)


async def send_daily_birthdays(bot) -> None:
    """
    Bugun tug‘ilgan kuni bo‘lgan insonlarga tabrik yuboradi.

    Yuborish tartibi:
    1. Alohida Premium Custom Emoji.
    2. Asosiy tug‘ilgan kun tabrigi.
    3. Tabrik musiqasi.

    Natijalar NotificationLog orqali qayd etiladi.
    """

    today = local_today()

    logger.info(
        "Tug‘ilgan kunlarni tekshirish boshlandi: %s",
        today,
    )

    async with SessionLocal() as session:

        # ====================================================
        # 1. BUGUN TUG‘ILGAN KUN BO‘LGAN INSONLARNI OLISH
        # ====================================================

        people = await birthdays_today(session, today)

        if not people:
            logger.info(
                "Bugun tug‘ilgan kuni bo‘lgan insonlar topilmadi."
            )
            return

        # ====================================================
        # 2. FAOL GURUHLARNI ANIQLASH
        # ====================================================

        result = await session.scalars(
            select(GroupConfig).where(
                GroupConfig.is_active.is_(True)
            )
        )

        configs = list(result.all())

        target_ids = list(
            dict.fromkeys(config.chat_id for config in configs)
        )

        if settings.target_group_id:
            if settings.target_group_id not in target_ids:
                target_ids.append(settings.target_group_id)

        if not target_ids:
            logger.warning(
                "Tabrik yuborish uchun guruh topilmadi. "
                "TARGET_GROUP_ID yoki /setgroup sozlamasini tekshiring."
            )
            return

        logger.info(
            "Bugungi tug‘ilgan kunlar: %s ta, "
            "maqsadli guruhlar: %s ta",
            len(people),
            len(target_ids),
        )

        # ====================================================
        # 3. HAR BIR INSON UCHUN TABRIK YUBORISH
        # ====================================================

        for person in people:

            # Avval muvaffaqiyatli yuborilgan tabrikni takrorlamaymiz.
            if await already_notified(
                session,
                person.id,
                today.year,
            ):
                logger.info(
                    "Tabrik avval muvaffaqiyatli qayd etilgan: "
                    "person_id=%s, year=%s",
                    person.id,
                    today.year,
                )
                continue

            text = make_greeting(person, today)

            sent_message_id = None

            successful_targets = 0
            failed_targets = []
            failed_emoji_targets = []

            # =================================================
            # 4. HAR BIR GURUHGA XABAR YUBORISH
            # =================================================

            for chat_id in target_ids:

                # ---------------------------------------------
                # 4.1. AVVAL PREMIUM EMOJI YUBORILADI
                # ---------------------------------------------

                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=PREMIUM_PARTY_EMOJI,
                        parse_mode="HTML",
                    )

                    logger.info(
                        "Premium bayram emojisi yuborildi: "
                        "person_id=%s, chat_id=%s",
                        person.id,
                        chat_id,
                    )

                except Exception:
                    failed_emoji_targets.append(chat_id)

                    logger.exception(
                        "Premium emoji yuborilmadi: "
                        "person_id=%s, chat_id=%s",
                        person.id,
                        chat_id,
                    )

                # ---------------------------------------------
                # 4.2. ASOSIY TABRIK YUBORILADI
                # ---------------------------------------------

                try:

                    if person.photo_file_id:

                        sent = await bot.send_photo(
                            chat_id=chat_id,
                            photo=person.photo_file_id,
                            caption=text,
                            parse_mode="HTML",
                        )

                    else:

                        sent = await bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode="HTML",
                        )

                    sent_message_id = sent.message_id
                    successful_targets += 1

                    logger.info(
                        "Asosiy tabrik yuborildi: "
                        "person_id=%s, chat_id=%s",
                        person.id,
                        chat_id,
                    )

                except Exception:

                    failed_targets.append(chat_id)

                    logger.exception(
                        "Asosiy tabrik yuborilmadi: "
                        "person_id=%s, chat_id=%s",
                        person.id,
                        chat_id,
                    )

                    continue

                # ---------------------------------------------
                # 4.3. TABRIK MUSIQASI YUBORILADI
                # ---------------------------------------------

                if person.music_file_id:

                    try:

                        await bot.send_audio(
                            chat_id=chat_id,
                            audio=person.music_file_id,
                            caption=(
                                f"🎵 {person.full_name} "
                                "uchun tabrik musiqasi"
                            ),
                        )

                        logger.info(
                            "Tabrik musiqasi yuborildi: "
                            "person_id=%s, chat_id=%s",
                            person.id,
                            chat_id,
                        )

                    except Exception:

                        logger.exception(
                            "Tabrik musiqasi yuborilmadi: "
                            "person_id=%s, chat_id=%s",
                            person.id,
                            chat_id,
                        )

            # =================================================
            # 5. NATIJANI NOTIFICATION LOG GA SAQLASH
            # =================================================

            try:

                log_entry = await session.scalar(
                    select(NotificationLog).where(
                        NotificationLog.person_id == person.id,
                        NotificationLog.birthday_year == today.year,
                    )
                )

                # Asosiy tabrik yuborilish holati.
                if successful_targets == len(target_ids):

                    status = "sent"

                elif successful_targets > 0:

                    status = "partial"

                else:

                    status = "failed"

                # Xatoliklarni qayd etish.
                error_messages = []

                if failed_targets:
                    error_messages.append(
                        "Asosiy tabrik yuborilmagan guruhlar: "
                        f"{failed_targets}"
                    )

                if failed_emoji_targets:
                    error_messages.append(
                        "Premium emoji yuborilmagan guruhlar: "
                        f"{failed_emoji_targets}"
                    )

                error_message = (
                    "\n".join(error_messages)[:2000]
                    if error_messages
                    else None
                )

                sent_at = (
                    datetime.now(ZoneInfo(settings.timezone))
                    if successful_targets > 0
                    else None
                )

                # Mavjud logni yangilash yoki yangi yaratish.
                if log_entry is None:

                    log_entry = NotificationLog(
                        person_id=person.id,
                        birthday_year=today.year,
                        status=status,
                        telegram_message_id=sent_message_id,
                        sent_at=sent_at,
                        error_message=error_message,
                    )

                    session.add(log_entry)

                else:

                    log_entry.status = status
                    log_entry.telegram_message_id = sent_message_id
                    log_entry.sent_at = sent_at
                    log_entry.error_message = error_message

                await session.commit()

                logger.info(
                    "Yuborish natijasi bazaga saqlandi: "
                    "person_id=%s, status=%s, "
                    "muvaffaqiyatli=%s, asosiy_xatolik=%s, "
                    "emoji_xatolik=%s",
                    person.id,
                    status,
                    successful_targets,
                    len(failed_targets),
                    len(failed_emoji_targets),
                )

            except Exception:

                await session.rollback()

                logger.exception(
                    "NotificationLog saqlanmadi: person_id=%s",
                    person.id,
                )

    logger.info(
        "Tug‘ilgan kunlarni tekshirish yakunlandi."
    )


# ============================================================
# APSCHEDULER SETUP
# ============================================================

def setup_scheduler(bot) -> AsyncIOScheduler:
    """
    Tug‘ilgan kun tabriklarini belgilangan vaqtda yuboradigan
    scheduler yaratadi.
    """

    try:

        hour, minute = map(
            int,
            settings.birthday_reminder_time.split(":"),
        )

    except (ValueError, AttributeError):

        raise ValueError(
            "BIRTHDAY_REMINDER_TIME noto‘g‘ri. "
            "Vaqt HH:MM formatida bo‘lishi kerak, masalan: 09:00"
        ) from None

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:

        raise ValueError(
            "BIRTHDAY_REMINDER_TIME soat 00–23 va minut 00–59 "
            "oralig‘ida bo‘lishi kerak."
        )

    timezone = ZoneInfo(settings.timezone)

    scheduler = AsyncIOScheduler(
        timezone=timezone
    )

    scheduler.add_job(
        send_daily_birthdays,
        trigger="cron",
        hour=hour,
        minute=minute,
        args=[bot],
        id="daily_birthdays",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    logger.info(
        "Tug‘ilgan kun scheduler sozlandi. "
        "Vaqt: %02d:%02d (%s)",
        hour,
        minute,
        settings.timezone,
    )

    return scheduler