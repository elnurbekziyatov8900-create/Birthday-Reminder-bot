from __future__ import annotations

import calendar
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import NotificationLog, Person


settings = get_settings()


# ============================================================
# TELEGRAM PREMIUM CUSTOM EMOJI
# ============================================================
# Faqat Telegram tomonidan berilgan haqiqiy custom_emoji_id ishlaydi.
# Quyidagi ID'lar oldin tekshirilgan. Oddiy Unicode emoji'ni
# <tg-emoji> ichiga joylash uni Premium emoji'ga aylantirmaydi.

CUSTOM_EMOJI_IDS: dict[str, str] = {
    "gift": "5199749070830197566",       # 🎁
    "party": "5436040291507247633",      # 🎉
    "sparkles": "5472164874886846699",   # ✨
    "star": "5435957248314579621",       # ⭐
    "trophy": "5409008750893734809",     # 🏆
}


def premium_emoji(key: str, fallback: str) -> str:
    """Telegram HTML formatida haqiqiy Custom Emoji qaytaradi."""
    emoji_id = CUSTOM_EMOJI_IDS.get(key, "").strip()

    if emoji_id.isdigit():
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

    return escape(fallback)


# ============================================================
# DATE AND AGE UTILITIES
# ============================================================

def birthday_date_for_year(birth_date: date, year: int) -> date:
    """29-fevral tug'ilgan kunini sozlamadagi siyosat bo'yicha hisoblaydi."""
    if (
        birth_date.month == 2
        and birth_date.day == 29
        and not calendar.isleap(year)
    ):
        if settings.leap_day_policy == "february_28":
            return date(year, 2, 28)
        return date(year, 3, 1)

    return date(year, birth_date.month, birth_date.day)


def age_on(birth_date: date, today: date) -> int:
    """Berilgan sanada inson nechchi yoshga kirganini hisoblaydi."""
    birthday_this_year = birthday_date_for_year(birth_date, today.year)

    if today >= birthday_this_year:
        return today.year - birth_date.year

    return today.year - birth_date.year - 1


def days_until(birth_date: date, today: date) -> int:
    """Keyingi tug'ilgan kungacha qolgan kunlar soni."""
    next_birthday = birthday_date_for_year(birth_date, today.year)

    if next_birthday < today:
        next_birthday = birthday_date_for_year(birth_date, today.year + 1)

    return (next_birthday - today).days


def local_today() -> date:
    """Bot sozlamasidagi vaqt zonasiga mos bugungi sana."""
    timezone = ZoneInfo(settings.timezone)
    return datetime.now(timezone).date()


# ============================================================
# PREMIUM BIRTHDAY GREETING
# ============================================================

def make_greeting(person: Person, today: date) -> str:
    """
    Oilaviy guruh uchun premium HTML tabrik tayyorlaydi.
    Greeting ichidagi bezak emojilari faqat tekshirilgan
    Telegram Custom Emoji ID'laridan foydalanadi.
    """
    name = escape(person.full_name, quote=True)
    age = age_on(person.birth_date, today)

    gift = premium_emoji("gift", "🎁")
    party = premium_emoji("party", "🎉")
    sparkles = premium_emoji("sparkles", "✨")
    star = premium_emoji("star", "⭐")
    trophy = premium_emoji("trophy", "🏆")

    if age <= 12:
        special_wish = (
            "Bolalik olamingiz doimo quvonch va beg'ubor kulguga to'lsin. "
            "Har bir orzuingiz amalga oshib, yangi kunlar sizga "
            "qiziqarli kashfiyotlar olib kelsin."
        )
    elif age <= 19:
        special_wish = (
            "Yoshlik davringiz unutilmas lahzalar, dadil orzular va "
            "yuksak natijalarga boy bo'lsin. Tanlagan yo'lingizda "
            "ishonch bilan olg'a boring."
        )
    elif age <= 35:
        special_wish = (
            "Oldingizga qo'ygan maqsadlaringiz birin-ketin amalga oshsin. "
            "Har bir yangi kun sizga yangi imkoniyat, xonadoningizga "
            "esa fayz va xotirjamlik olib kelsin."
        )
    else:
        special_wish = (
            "Umringiz uzoq, taningiz sog', ko'nglingiz xotirjam bo'lsin. "
            "Yaqinlaringiz mehrini, farzandlar kamolini va hayotning "
            "go'zal onlaridan bahramand bo'lib yuring."
        )

    poem = (
        "Yuzingizdan arimasin kulgu, shodlik,"
        "Har kuningiz olib kelsin baxt, omad."
        "Ko'nglingizda yashnasin doim ezgulik,"
        "Umringizga hamroh bo'lsin saodat."
    )

    return (
        f"{party} <b>BUGUN — QADRLI KUN!</b> {party}\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{sparkles} <b>{name}</b> {sparkles}\n"
        "\n"
        f"<b>{age} YOSHINGIZ MUBORAK BO'LSIN!</b>\n"
        f"{star} Bugun hayotingizning yana bir go'zal sahifasi boshlandi.\n"
        f"{gift} Tug'ilgan sana: <b>{person.birth_date:%d.%m.%Y}</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{sparkles} <b>ENG EZGU TILAKLAR</b> {sparkles}\n"
        "\n"
        "Sizga mustahkam sog'liq, qalb xotirjamligi, oilaviy baxt, "
        "baraka va barcha ezgu niyatlaringiz ro'yobini tilaymiz.\n"
        "\n"
        f"{special_wish}\n"
        "\n"
        "Har doim yaqinlaringiz ardog'ida, mehr va e'tibor qurshovida "
        "bo'ling. Hayotingiz quvonchli xotiralarga boy bo'lsin!\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{star} <b>SIZ UCHUN SAMIMIY TO'RTLIK</b> {star}\n"
        "\n"
        f"<blockquote>{escape(poem)}</blockquote>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{gift} <b>TAVALLUD KUNINGIZ MUBORAK!</b> {gift}\n"
        "\n"
        "<i>Oilamiz nomidan cheksiz mehr va eng yaxshi tilaklar bilan.</i>\n"
        f"{trophy} <b>Yangi yoshingiz yangi zafarlar olib kelsin!</b>"
    )


# ============================================================
# PEOPLE DATABASE QUERIES
# ============================================================

async def list_people(session: AsyncSession) -> list[Person]:
    """Bazadagi barcha faol insonlarni qaytaradi."""
    result = await session.scalars(
        select(Person)
        .where(Person.is_active.is_(True))
        .order_by(Person.full_name.asc())
    )
    return list(result.all())


async def birthdays_today(session: AsyncSession, today: date) -> list[Person]:
    """Bugun tug'ilgan kuni bo'lgan faol insonlarni qaytaradi."""
    people = await list_people(session)

    return [
        person
        for person in people
        if birthday_date_for_year(person.birth_date, today.year) == today
    ]


async def already_notified(
    session: AsyncSession,
    person_id: int,
    year: int,
) -> bool:
    """
    Shu yil uchun muvaffaqiyatli yuborilgan tabrikni tekshiradi.
    Modeldagi to'g'ri ustun nomi birthday_year.
    """
    result = await session.scalar(
        select(NotificationLog).where(
            NotificationLog.person_id == person_id,
            NotificationLog.birthday_year == year,
            NotificationLog.status == "sent",
        )
    )
    return result is not None


# ============================================================
# BIRTHDAY TABLE
# ============================================================

def birthday_table(people: list[Person], today: date) -> str:
    """Tug'ilgan kunlar ro'yxatini HTML formatida chiqaradi."""
    if not people:
        return "<b>Hozircha ma'lumot mavjud emas.</b>"

    party = premium_emoji("party", "🎉")
    gift = premium_emoji("gift", "🎁")
    star = premium_emoji("star", "⭐")

    lines = [
        f"{party} <b>OILAVIY TUG'ILGAN KUNLAR</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    sorted_people = sorted(
        people,
        key=lambda person: (
            days_until(person.birth_date, today),
            person.full_name.casefold(),
        ),
    )

    for index, person in enumerate(sorted_people, start=1):
        name = escape(person.full_name, quote=True)
        age = age_on(person.birth_date, today)
        remaining = days_until(person.birth_date, today)

        if remaining == 0:
            status = f"{party} <b>BUGUN!</b>"
        elif remaining == 1:
            status = "Ertaga"
        else:
            status = f"{remaining} kun qoldi"

        lines.append(
            f"{index}. {star} <b>{name}</b>\n"
            f"   Sana: <code>{person.birth_date:%d.%m.%Y}</code>\n"
            f"   Yosh: <b>{age}</b> | {status}"
        )

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            f"{gift} Jami: <b>{len(sorted_people)} nafar</b>",
            f"Bugungi sana: <code>{today:%d.%m.%Y}</code>",
        ]
    )

    return "\n".join(lines)
