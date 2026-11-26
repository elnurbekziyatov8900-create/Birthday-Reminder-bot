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

# Har bir yosh guruhi uchun bir nechta samimiy tilak. Har yili (va har
# bir inson uchun) boshqa variant tanlanadi — tabriklar bir xil takrorlanib,
# "robotdek" ko'rinmasligi uchun.
WISHES: dict[str, tuple[str, ...]] = {
    "child": (
        "Jajji quvonchimiz! Sen bilan uyimiz yanada yorug', kunlarimiz "
        "yanada shirin. Doim sog'-salomat bo'l, katta-katta orzularing "
        "ushalsin, beg'ubor kulging hech qachon so'nmasin!",
        "Oilamizning erkatoyi! Sening ulg'ayib borayotganingni ko'rish biz "
        "uchun eng katta baxt. Aqlli, odobli va baxtli bo'lib o'sgin, har "
        "bir kuning o'yin-kulgu va yangi kashfiyotlarga to'la bo'lsin!",
    ),
    "teen": (
        "Yoshlikning eng go'zal pallasidasiz. Orzularingiz baland, "
        "yo'lingiz ochiq bo'lsin. O'qishda, hayotda va boshlagan har bir "
        "ishingizda omad yor bo'lib, biz doim sizdan faxrlanib yuraylik!",
        "Har bir yangi yosh — yangi imkoniyat. Ishonchingiz mustahkam, "
        "qadamingiz dadil bo'lsin. Do'stlaringiz sadoqatli, ustozlaringiz "
        "mamnun, ota-onangiz esa doim sizdan rozi bo'lsin!",
    ),
    "young": (
        "Siz oilamizning faxri va tayanchisiz. Hayotingizdagi har bir kun "
        "mazmunli, har bir qadamingiz barakali bo'lsin. Niyat qilgan "
        "maqsadlaringizga yetib, xonadoningiz fayz va quvonchga to'lsin!",
        "Yangi yoshingiz sizga yangi kuch, yangi ilhom va yangi "
        "g'alabalar olib kelsin. Mehnatingiz samarasini ko'rib, "
        "yaqinlaringiz bilan baxtli damlarni ko'p bor baham ko'ring!",
    ),
    "adult": (
        "Siz oilamizning mehribon tayanchi va iliq qalbisiz. Bergan "
        "mehringiz, qilgan yaxshiliklaringiz o'n chandon bo'lib qaytsin. "
        "Sog'lik, xotirjamlik va farzandlar rohatini ko'rib yuring!",
        "Bosib o'tgan har bir yilingiz biz uchun ibrat. Dasturxoningiz "
        "to'kin, uyingiz fayzli, ko'nglingiz doim tinch bo'lsin. "
        "Yaqinlaringizning duosi va mehri sizni hamisha asrasin!",
    ),
    "elder": (
        "Siz oilamizning duoli boshi, eng aziz insonimizsiz. Umringiz "
        "uzoq, sog'lig'ingiz mustahkam bo'lsin. Farzandlar va nevaralar "
        "kamolini ko'rib, ularning mehri qurshovida baxtiyor yashang!",
        "Sizning duolaringiz — oilamizning eng katta boyligi. Alloh sizga "
        "uzoq umr, sihat-salomatlik va qalb xotirjamligini ato etsin. Har "
        "bir kuningiz quvonch va hurmat bilan o'tsin!",
    ),
}

POEMS: tuple[tuple[str, ...], ...] = (
    (
        "Yuzingizdan arimasin kulgu, shodlik,",
        "Har kuningiz olib kelsin baxt, omad.",
        "Ko'nglingizda yashnasin doim ezgulik,",
        "Umringizga hamroh bo'lsin saodat.",
    ),
    (
        "Gullar kabi yashnasin har bir kuningiz,",
        "Quyosh kabi porlasin yorug' yuzingiz.",
        "Baxt-u omad hamisha bo'lsin yo'ldoshingiz,",
        "Hamisha baland bo'lsin boshingiz.",
    ),
    (
        "Bugun sizning kuningiz, olam to'la quvonch,",
        "Yaqinlaringiz mehri — eng ishonchli tayanch.",
        "Har yangi tong sizga nur va omad keltirsin,",
        "Qalbingizdagi orzular birma-bir ushalsin.",
    ),
)

# Bolalarga "sen" deb, erkalab murojaat qilinadi.
CHILD_POEM: tuple[str, ...] = (
    "Gullar kabi yashnasin har bir kuning,",
    "Quyosh kabi porlasin yorug' yuzing.",
    "Baxt-u omad hamisha bo'lsin yo'ldoshing,",
    "Kulib tursin doimo shirin so'zing.",
)

# 40 yoshdan kattalar uchun — hurmat va ehtirom ruhidagi she'rlar.
MATURE_POEMS: tuple[tuple[str, ...], ...] = (
    (
        "Siz bizning g'ururimiz, oilamiz chirog'i,",
        "Mehringiz — xonadonning eng iliq quchog'i.",
        "Umringiz uzoq bo'lsin, ko'nglingiz doim butun,",
        "Har kuningiz bayramdek o'tsin xuddi bugun.",
    ),
    (
        "Bosib o'tgan yo'llaringiz nurga to'lsin,",
        "Har bir aytgan duongiz ijobat bo'lsin.",
        "Farzandlar kamolidan ko'nglingiz to'lsin,",
        "Umringiz uzoq, baxtingiz bardavom bo'lsin.",
    ),
)

# 50 yoshdan kattalar uchun qo'shimcha she'r.
ELDER_POEM: tuple[str, ...] = (
    "Har bir oq tolangizda hikmat bor, sabr bor,",
    "Har bir duoingizda oilaga madad bor.",
    "Nevaralar kulgusi qalbingizga nur bo'lsin,",
    "Umringiz uzoq bo'lib, dasturxoningiz to'lsin.",
)

RESPECT_AGE = 40  # shu yoshdan boshlab "Muhtaram" deb murojaat qilinadi
ELDER_POEM_AGE = 50  # shu yoshdan boshlab qo'shimcha she'r qo'shiladi


def _age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teen"
    if age <= 35:
        return "young"
    if age <= 59:
        return "adult"
    return "elder"


def _pick(options: tuple, person_id: int, year: int, salt: int = 0):
    # Tasodifiy emas, balki barqaror tanlov: qayta urinishda ham, test va
    # haqiqiy tabrikda ham bir xil matn chiqadi.
    return options[(person_id * 7 + year + salt) % len(options)]


def _display_name(full_name: str, age: int) -> str:
    name = f"<b>{safe(full_name)}</b>"
    return f"Muhtaram {name}" if age >= RESPECT_AGE else name


def _poems_for(age: int, person_id: int, year: int) -> list[tuple[str, ...]]:
    if age <= 12:
        return [CHILD_POEM]

    if age < RESPECT_AGE:
        return [_pick(POEMS, person_id, year, 1)]

    poems = [_pick(MATURE_POEMS, person_id, year, 1)]

    if age >= ELDER_POEM_AGE:
        poems.append(ELDER_POEM)

    return poems


def _divider() -> str:
    return f"{e('sparkles')} ┈┈┈┈┈┈┈┈┈┈┈┈┈┈ {e('sparkles')}"


def make_greeting_caption(person: Person | PersonData, today: date) -> str:
    """Juda uzun ism bo'lgan holat uchun qisqa sarlavha."""

    age = turning_age(person.birth_date, today)

    return (
        f"{e('fireworks')} <b>Bugun oilamizning quvonchli kuni!</b> "
        f"{e('fireworks')}\n\n"
        f"{e('crown') if age >= RESPECT_AGE else e('glowing_star')} "
        f"{_display_name(person.full_name, age)} bugun "
        f"<b>{age} yoshni</b> qarshi olmoqda! {e('partying_face')}"
    )


def make_greeting(
    person: Person | PersonData,
    today: date,
    compact: bool = False,
) -> str:
    """Samimiy tabrik matni.

    ``compact=True`` bo'lsa she'rlar tushirib qoldiriladi — juda uzun ism
    bilan ham matn surat ostiga (1024 belgi) sig'ishi uchun.
    """

    # Tug'ilgan kunning o'zida bu bugungi yosh; /testbirthday boshqa kuni
    # ishlatilsa ham navbatdagi (to'ladigan) yosh ko'rsatiladi.
    age = turning_age(person.birth_date, today)
    group = _age_group(age)
    is_child = group == "child"
    respected = age >= RESPECT_AGE

    wish = _pick(WISHES[group], person.id, today.year)

    if is_child:
        badge, poem_icon, poem_title = e("teddy"), e("rainbow"), "Sen uchun she'r"
        closing = "Tug'ilgan kuning muborak, jonim!"
        signature = "Seni juda yaxshi ko'radigan oilang"
    elif respected:
        badge, poem_icon, poem_title = e("crown"), e("rose"), "Siz uchun she'r"
        closing = "Tavallud kuningiz muborak bo'lsin!"
        signature = "Sizni chin dildan hurmat qiluvchi oilangiz"
    else:
        badge, poem_icon, poem_title = e("glowing_star"), e("blossom"), "Siz uchun she'r"
        closing = "Tavallud kuningiz muborak bo'lsin!"
        signature = "Sizni chin dildan sevuvchi oilangiz"

    poem_section = ""

    if not compact:
        poems = _poems_for(age, person.id, today.year)

        if len(poems) > 1:
            poem_title = "Siz uchun she'rlar"

        poem_section = (
            f"{poem_icon} <b>{poem_title}</b>\n"
            + "\n".join(
                quote("<i>" + "\n".join(safe(line) for line in poem) + "</i>")
                for poem in poems
            )
            + "\n\n"
        )

    return (
        f"{e('balloon')}{e('confetti')}{e('party')}{e('cake')}"
        f"{e('party')}{e('confetti')}{e('balloon')}\n"
        f"{e('fireworks')} <b>Bugun oilamizning quvonchli kuni!</b> "
        f"{e('fireworks')}\n"
        f"{_divider()}\n"
        "\n"
        f"{badge} {_display_name(person.full_name, age)} bugun "
        f"<b>{age} yoshni</b> qarshi olmoqda! {e('partying_face')}\n"
        "\n"
        f"{e('sparkling_heart')} <b>Qalbimizdan chiqqan tilaklar:</b>\n"
        + quote(safe(wish))
        + "\n\n"
        + poem_section
        + f"{_divider()}\n"
        f"{e('gift')} <b>{closing}</b> {e('cake')}\n"
        f"{e('heart_hands')} {hint(signature)} {e('heart')}"
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
