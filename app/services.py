from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Person
from app.ui import DIVIDER, e, hint, quote, safe


settings = get_settings()

MONTHS_UZ = (
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
)


@dataclass(frozen=True, slots=True)
class PersonData:
    """ORM obyektidan mustaqil nusxa.

    Sessiya rollback/commit qilinganda ORM obyektlari "expired" bo'lib
    qoladi va async rejimda ularning atributlarini o'qish xatolikka olib
    keladi. Shuning uchun yuborish jarayonida shu nusxadan foydalaniladi.
    """

    id: int
    full_name: str
    birth_date: date
    photo_file_id: str | None
    music_file_id: str | None

    @classmethod
    def from_person(cls, person: Person) -> "PersonData":
        return cls(
            id=person.id,
            full_name=person.full_name,
            birth_date=person.birth_date,
            photo_file_id=person.photo_file_id,
            music_file_id=person.music_file_id,
        )


# ================================================================
# SANA HISOB-KITOBLARI
# ================================================================

def birthday_date_for_year(birth_date: date, year: int) -> date:
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
    birthday_this_year = birthday_date_for_year(birth_date, today.year)

    if today >= birthday_this_year:
        return today.year - birth_date.year

    return today.year - birth_date.year - 1


def next_birthday(birth_date: date, today: date) -> date:
    upcoming = birthday_date_for_year(birth_date, today.year)

    if upcoming < today:
        upcoming = birthday_date_for_year(birth_date, today.year + 1)

    return upcoming


def days_until(birth_date: date, today: date) -> int:
    return (next_birthday(birth_date, today) - today).days


def turning_age(birth_date: date, today: date) -> int:
    """Navbatdagi tug'ilgan kunda to'ladigan yosh."""

    return next_birthday(birth_date, today).year - birth_date.year


def local_today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def format_date_uz(value: date) -> str:
    return f"{value.day}-{MONTHS_UZ[value.month - 1]}, {value.year}"


def format_day_month_uz(value: date) -> str:
    return f"{value.day}-{MONTHS_UZ[value.month - 1]}"


# ================================================================
# TABRIK MATNI
# ================================================================

def _special_wish(age: int) -> str:
    if age <= 12:
        return (
            "Bolalik olamingiz doimo quvonch va beg'ubor kulguga to'lsin. "
            "Har bir orzuingiz ushalib, har yangi kun sizga qiziqarli "
            "kashfiyotlar olib kelsin."
        )

    if age <= 19:
        return (
            "Yoshlik davringiz unutilmas lahzalar, dadil orzular va "
            "yuksak natijalarga boy bo'lsin. Tanlagan yo'lingizda "
            "ishonch bilan olg'a boring."
        )

    if age <= 35:
        return (
            "Oldingizga qo'ygan maqsadlaringiz birin-ketin amalga oshsin. "
            "Har bir yangi kun sizga yangi imkoniyat, xonadoningizga "
            "esa fayz va xotirjamlik olib kelsin."
        )

    return (
        "Umringiz uzoq, taningiz sog', ko'nglingiz xotirjam bo'lsin. "
        "Yaqinlaringiz mehrini, farzandlar kamolini ko'rib, hayotning "
        "go'zal onlaridan bahramand bo'lib yuring."
    )


POEM_LINES = (
    "Yuzingizdan arimasin kulgu, shodlik,",
    "Har kuningiz olib kelsin baxt, omad.",
    "Ko'nglingizda yashnasin doim ezgulik,",
    "Umringizga hamroh bo'lsin saodat.",
)


def make_greeting_caption(person: Person | PersonData, today: date) -> str:
    """Surat ostiga qo'yiladigan qisqa (1024 belgidan kam) sarlavha."""

    age = age_on(person.birth_date, today)

    return (
        f"{e('confetti')} {e('cake')} {e('confetti')}\n"
        f"<b>{safe(person.full_name)}</b>\n"
        f"{e('balloon')} <b>{age} yoshingiz muborak!</b> {e('balloon')}"
    )


def make_greeting(
    person: Person | PersonData,
    today: date,
    compact: bool = False,
) -> str:
    """To'liq tabrik matni.

    ``compact=True`` bo'lsa to'rtlik qismi tushirib qoldiriladi — juda uzun
    ism bilan ham matn surat ostiga (1024 belgi) sig'ishi uchun.
    """

    name = safe(person.full_name)
    age = age_on(person.birth_date, today)
    poem = "\n".join(safe(line) for line in POEM_LINES)

    poem_section = (
        ""
        if compact
        else (
            f"{e('bouquet')} <b>Siz uchun samimiy to'rtlik</b>\n"
            + quote(f"<i>{poem}</i>")
            + "\n\n"
        )
    )

    return (
        f"{e('confetti')}{e('party')}{e('cake')}{e('party')}{e('confetti')}\n"
        f"<b>TAVALLUD KUNINGIZ MUBORAK!</b>\n"
        f"{DIVIDER}\n"
        "\n"
        f"{e('crown')} <b>{name}</b>\n"
        f"{e('balloon')} Bugun siz <b>{age} yoshga</b> to'ldingiz!\n"
        f"{e('calendar')} {format_date_uz(person.birth_date)}\n"
        "\n"
        f"{e('sparkles')} <b>Eng ezgu tilaklarimiz</b>\n"
        + quote(
            "Sizga mustahkam sog'liq, qalb xotirjamligi, oilaviy baxt, "
            "baraka va barcha ezgu niyatlaringiz ro'yobini tilaymiz.\n\n"
            f"{_special_wish(age)}\n\n"
            "Har doim yaqinlaringiz ardog'ida, mehr va e'tibor "
            "qurshovida bo'ling!"
        )
        + "\n\n"
        + poem_section
        + f"{DIVIDER}\n"
        f"{e('heart_gift')} {hint('Oilamiz nomidan cheksiz mehr bilan')}\n"
        f"{e('trophy')} <b>Yangi yoshingiz yangi zafarlar olib kelsin!</b> "
        f"{e('glowing_star')}"
    )


def music_caption(full_name: str) -> str:
    return (
        f"{e('notes')} <b>{safe(full_name)}</b> uchun tabrik qo'shig'i "
        f"{e('heart')}"
    )


# ================================================================
# MA'LUMOTLAR BAZASI
# ================================================================

async def list_people(session: AsyncSession) -> list[Person]:
    result = await session.scalars(
        select(Person)
        .where(Person.is_active.is_(True))
        .order_by(Person.full_name.asc())
    )

    return list(result.all())


async def birthdays_today(
    session: AsyncSession,
    today: date,
) -> list[Person]:
    people = await list_people(session)

    return [
        person
        for person in people
        if birthday_date_for_year(person.birth_date, today.year) == today
    ]


def sort_by_upcoming(people: list[Person], today: date) -> list[Person]:
    return sorted(
        people,
        key=lambda person: (
            days_until(person.birth_date, today),
            person.full_name.casefold(),
        ),
    )


# ================================================================
# RO'YXAT DIZAYNI
# ================================================================

def _status_line(person: Person, today: date) -> str:
    remaining = days_until(person.birth_date, today)
    turning = turning_age(person.birth_date, today)

    if remaining == 0:
        return f"{e('party')} <b>BUGUN!</b> · {turning} yosh"

    if remaining == 1:
        return f"{e('bell')} <b>Ertaga</b> · {turning} yosh bo'ladi"

    return f"{e('hourglass')} {remaining} kun qoldi · {turning} yosh bo'ladi"


def person_entry(person: Person, today: date) -> str:
    return (
        f"{e('star')} <b>{safe(person.full_name)}</b>  "
        f"<code>#{person.id}</code>\n"
        f"{e('calendar')} {format_day_month_uz(person.birth_date)} "
        f"<i>({person.birth_date:%d.%m.%Y})</i>\n"
        f"{_status_line(person, today)}"
    )


def birthday_table(
    people: list[Person],
    today: date,
    heading: str = "OILAVIY TUG'ILGAN KUNLAR",
) -> str:
    if not people:
        return f"{e('mailbox')} <b>Hozircha ma'lumot mavjud emas.</b>"

    sorted_people = sort_by_upcoming(people, today)

    # Har bir yozuv "\n\n" bilan ajratiladi: uzun ro'yxat bo'laklarga
    # bo'linganda HTML teglar buzilmaydi.
    blocks = [
        f"{e('cake')} <b>{safe(heading)}</b>\n{DIVIDER}",
        *(person_entry(person, today) for person in sorted_people),
        (
            f"{DIVIDER}\n"
            f"{e('people')} Jami: <b>{len(sorted_people)} nafar</b>\n"
            f"{e('calendar')} Bugun: <b>{format_date_uz(today)}</b>"
        ),
    ]

    return "\n\n".join(blocks)
