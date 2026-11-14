import calendar
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Person, NotificationLog

settings = get_settings()


def age_on(birth_date: date, today: date) -> int:
    """Return the age the person has reached by `today`."""
    birthday_has_passed = (today.month, today.day) >= (birth_date.month, birth_date.day)
    return today.year - birth_date.year - (0 if birthday_has_passed else 1)


def birthday_date_for_year(birth_date: date, year: int) -> date:
    """Policy for Feb 29 birthdays in non-leap years is configurable."""
    if birth_date.month == 2 and birth_date.day == 29 and not calendar.isleap(year):
        if settings.leap_day_policy == "february_28":
            return date(year, 2, 28)
        return date(year, 3, 1)
    return date(year, birth_date.month, birth_date.day)


def days_until(birth_date: date, today: date) -> int:
    next_day = birthday_date_for_year(birth_date, today.year)
    if next_day < today:
        next_day = birthday_date_for_year(birth_date, today.year + 1)
    return (next_day - today).days


def make_greeting(person: Person, today: date) -> str:
    """HTML-formatted greeting designed to fit a Telegram photo caption."""
    age = age_on(person.birth_date, today)
    name = escape(person.full_name)
    poem = (
        "Bugun quvonch to‘lsin xonadoningizga,\n"
        "Baxt va omad kulsin har bir kuningizda.\n"
        "Sog‘lik, mehr hamroh bo‘lsin umrbod,\n"
        "Yorug‘ bo‘lsin doim bosgan yo‘lingiz! 🌹"
    )
    return (
        "🎉 <b>BUGUN OILAMIZNING QUVONCHLI KUNI!</b> 🎂\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <b>{name}</b> ✨\n"
        f"🎈 Bugun <b>{age} yoshni</b> qarshi olmoqda!\n"
        f"📅 Tug‘ilgan sana: <b>{person.birth_date:%d.%m.%Y}</b>\n\n"
        "💐 <b>Samimiy tilaklarimiz</b>\n"
        "Sizga mustahkam sog‘liq, cheksiz baxt, oilaviy xotirjamlik "
        "va barcha ezgu orzularingiz ro‘yobini tilaymiz. Har doim "
        "yaqinlaringiz mehrida, yuzingizda tabassum bilan yuring! ❤️\n\n"
        "📝 <b>TAVALLUD KUNIGA SHE’R</b>\n"
        f"<blockquote>{escape(poem)}</blockquote>\n"
        "🎁 <b>TAVALLUD KUNINGIZ MUBORAK BO‘LSIN!</b> 🎊\n"
        "<i>Oilamiz nomidan eng samimiy tilaklar!</i> 💖"
    )


async def list_people(session: AsyncSession) -> list[Person]:
    result = await session.scalars(
        select(Person)
        .where(Person.is_active.is_(True))
        .order_by(Person.birth_date, Person.full_name)
    )
    return list(result.all())


async def birthdays_today(session: AsyncSession, today: date) -> list[Person]:
    people = await list_people(session)
    return [
        person for person in people
        if birthday_date_for_year(person.birth_date, today.year) == today
    ]


async def already_notified(session: AsyncSession, person_id: int, year: int) -> bool:
    result = await session.scalar(
        select(NotificationLog.id).where(
            NotificationLog.person_id == person_id,
            NotificationLog.birthday_year == year,
            NotificationLog.status == "sent",
        )
    )
    return result is not None


def local_today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def birthday_table(people: list[Person], today: date) -> str:
    """Telegram-friendly calendar: aligned text blocks, not a true HTML table."""
    if not people:
        return (
            "📅 <b>OILAVIY TUG‘ILGAN KUNLAR</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Hozircha bazada insonlar yo‘q.\n"
            "Yangi inson qo‘shish uchun /add buyrug‘ini yuboring."
        )

    ordered = sorted(
        people,
        key=lambda p: (days_until(p.birth_date, today), p.full_name.casefold()),
    )
    lines = [
        "🗓 <b>OILAVIY TUG‘ILGAN KUNLAR KALENDARI</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "<i>Sana · yosh · keyingi tug‘ilgan kungacha</i>",
        "",
    ]
    for index, person in enumerate(ordered, 1):
        days = days_until(person.birth_date, today)
        status = "🎂 <b>BUGUN!</b>" if days == 0 else f"⏳ {days} kun qoldi"
        age = age_on(person.birth_date, today)
        lines.append(
            f"🔹 <b>{index}. {escape(person.full_name)}</b>\n"
            f"   📆 {person.birth_date:%d.%m.%Y}  ·  🎈 {age} yosh\n"
            f"   {status}"
        )
    lines.extend(["", "❤️ <i>Family Birthday Assistant</i>"])
    return "\n\n".join(lines)
