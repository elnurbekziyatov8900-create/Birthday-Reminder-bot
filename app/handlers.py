from __future__ import annotations

import hmac
import logging
import mimetypes
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import SessionLocal
from app.messaging import (
    get_active_groups,
    migrate_group_chat_id,
    send_birthday_greeting,
    split_html_text,
)
from app.models import AuthUser, GroupConfig, Person
from app.services import (
    PersonData,
    age_on,
    birthday_date_for_year,
    birthday_table,
    days_until,
    format_date_uz,
    list_people,
    local_today,
    sort_by_upcoming,
    turning_age,
)
from app.ui import DIVIDER, card, e, hint, quote, row, safe, title

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()

MAX_PASSWORD_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
MAX_NAME_LENGTH = 200
MAX_AUDIO_SIZE = 20 * 1024 * 1024
UPCOMING_DAYS = 30


class AuthStates(StatesGroup):
    waiting_password = State()


class AddStates(StatesGroup):
    name = State()
    birth_date = State()


class EditStates(StatesGroup):
    name = State()
    birth_date = State()


class MediaStates(StatesGroup):
    waiting_photo = State()
    waiting_audio = State()


# ================================================================
# MATNLAR
# ================================================================

CANCEL_HINT = hint("Bekor qilish: /cancel")

WELCOME_TEXT = card(
    title("cake", "Family Birthday Assistant"),
    f"{e('wave')} Assalomu alaykum!\n"
    "Oilangiz uchun muhim sanalarni eslab qolish endi oson.",
    f"{e('lock')} Davom etish uchun <b>kirish parolini</b> yuboring.\n"
    f"{CANCEL_HINT}",
)

MENU_SHORT = (
    f"{e('calendar')} /birthdays — barcha tug'ilgan kunlar\n"
    f"{e('party')} /today — bugungi tabriklar\n"
    f"{e('hourglass')} /next — eng yaqin sana\n"
    f"{e('bell')} /upcoming — keyingi {UPCOMING_DAYS} kun\n"
    f"{e('plus')} /add — yangi inson qo'shish\n"
    f"{e('chart')} /status — tizim holati\n"
    f"{e('memo')} /help — to'liq qo'llanma"
)

AUTH_SUCCESS_TEXT = card(
    title("check", "Avtorizatsiya muvaffaqiyatli!"),
    f"{e('sparkles')} Family Birthday Assistant xizmatiga xush kelibsiz.",
    MENU_SHORT,
)

HELP_TEXT = card(
    title("cake", "Family Birthday Assistant"),
    hint("Boshqaruv qo'llanmasi"),
    f"{e('calendar')} <b>TUG'ILGAN KUNLAR</b>\n"
    + quote(
        "/birthdays — barcha faol tug'ilgan kunlar\n"
        "/today — bugungi tug'ilgan kunlar\n"
        "/next — navbatdagi tug'ilgan kun\n"
        f"/upcoming — keyingi {UPCOMING_DAYS} kun ichidagi sanalar"
    ),
    f"{e('person')} <b>MA'LUMOTLARNI BOSHQARISH</b>\n"
    + quote(
        "/add — yangi inson qo'shish\n"
        "/edit ID — ma'lumotlarni tahrirlash\n"
        "/delete ID — insonni arxivlash\n"
        "/setphoto ID — surat biriktirish\n"
        "/setmusic ID — musiqa biriktirish"
    ),
    f"{e('family')} <b>GURUH VA TABRIKLAR</b>\n"
    + quote(
        "/setgroup — joriy guruhni asosiy guruh qilish\n"
        "/groups — ulangan guruhlar\n"
        "/chatid — joriy chat ID sini ko'rish\n"
        "/testbirthday ID — test tabrigini yuborish"
    ),
    f"{e('robot')} <b>TIZIM</b>\n"
    + quote(
        "/status — bot va baza holati\n"
        "/cancel — joriy amalni bekor qilish\n"
        "/help — ushbu qo'llanma"
    ),
)


def _usage(emoji_key: str, command: str, example: str) -> str:
    return (
        f"{e(emoji_key)} Foydalanish: <code>{command}</code>\n"
        f"{hint('Masalan:')} <code>{example}</code>"
    )


# ================================================================
# YORDAMCHILAR
# ================================================================

def _parse_person_id(message: Message) -> int | None:
    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        return None

    person_id = int(parts[1])

    return person_id if person_id > 0 else None


def _parse_birth_date(raw_value: str) -> date | None:
    try:
        parsed = datetime.strptime(raw_value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None

    if parsed.year < 1900 or parsed > local_today():
        return None

    return parsed


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _password_matches(raw_password: str) -> bool:
    # Vaqtga asoslangan hujumlardan himoya uchun constant-time taqqoslash.
    return hmac.compare_digest(
        raw_password.encode("utf-8"),
        settings.bot_access_password.encode("utf-8"),
    )


async def authorized(user_id: int) -> bool:
    if user_id not in settings.admin_ids:
        return False

    async with SessionLocal() as session:
        user = await session.scalar(
            select(AuthUser).where(AuthUser.telegram_user_id == user_id)
        )

        return bool(user and user.is_authenticated)


async def require_admin(message: Message) -> bool:
    if message.chat.type != "private":
        await message.answer(
            f"{e('lock')} <b>Bu komanda shaxsiy chatda boshqariladi.</b>\n"
            "Bot bilan shaxsiy chatga o'ting va /start yuboring."
        )
        return False

    if not message.from_user:
        return False

    if message.from_user.id not in settings.admin_ids:
        await message.answer(f"{e('cross')} <b>Kirishga ruxsat yo'q.</b>")
        return False

    if not await authorized(message.from_user.id):
        await message.answer(
            f"{e('lock')} Avval avtorizatsiyadan o'ting: /start"
        )
        return False

    return True


async def _get_active_person(session: Any, person_id: int) -> Person | None:
    person = await session.get(Person, person_id)

    if person is None or not person.is_active:
        return None

    return person


async def _send_long_text(message: Message, text: str) -> None:
    for chunk in split_html_text(text):
        await message.answer(chunk)


def _not_found_text() -> str:
    return (
        f"{e('cross')} <b>Inson topilmadi.</b>\n"
        "ID noto'g'ri yoki ushbu inson arxivlangan.\n"
        + hint("Ro'yxat: /birthdays")
    )


# ================================================================
# AUTENTIFIKATSIYA
# ================================================================

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    await state.clear()

    if current_state is None:
        await message.answer(
            f"{e('bulb')} Hozir bekor qilinadigan faol jarayon yo'q."
        )
        return

    await message.answer(
        f"{e('check')} <b>Joriy jarayon bekor qilindi.</b>\n"
        f"{hint('Davom etish uchun /help')}"
    )


@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer(
            f"{e('lock')} Iltimos, botni shaxsiy chatda ochib, /start yuboring."
        )
        return

    if not message.from_user:
        return

    user_id = message.from_user.id

    if user_id not in settings.admin_ids:
        await state.clear()
        await message.answer(
            f"{e('cross')} <b>Kirishga ruxsat yo'q.</b>\n\n"
            "Ushbu bot faqat ruxsat berilgan administrator uchun mo'ljallangan."
        )
        return

    if await authorized(user_id):
        await state.clear()
        await message.answer(
            card(
                title("cake", "Family Birthday Assistant"),
                f"{e('wave')} Qayta xush kelibsiz! Bot ishlashga tayyor.",
                MENU_SHORT,
            )
        )
        return

    await state.set_state(AuthStates.waiting_password)
    await message.answer(WELCOME_TEXT)


@router.message(AuthStates.waiting_password, F.text)
async def password_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id not in settings.admin_ids:
        await state.clear()
        return

    raw_password = (message.text or "").strip()

    try:
        await message.delete()
    except TelegramAPIError:
        logger.debug("Parol xabarini o'chirish imkoni bo'lmadi.")

    if raw_password.startswith("/"):
        await message.answer(
            f"{e('lock')} <b>Parol kutilmoqda.</b>\n"
            f"Parolni yuboring yoki /cancel orqali bekor qiling."
        )
        return

    async with SessionLocal() as session:
        user = await session.scalar(
            select(AuthUser).where(
                AuthUser.telegram_user_id == message.from_user.id
            )
        )

        if user is None:
            user = AuthUser(
                telegram_user_id=message.from_user.id,
                is_authenticated=False,
                role="admin",
                failed_attempts=0,
            )
            session.add(user)
            await session.flush()

        now = _now_utc()

        if user.locked_until:
            locked_until = _normalize_datetime(user.locked_until)

            if locked_until > now:
                minutes = max(
                    1,
                    (int((locked_until - now).total_seconds()) + 59) // 60,
                )
                await state.clear()
                await message.answer(
                    f"{e('lock')} <b>Kirish vaqtincha bloklangan.</b>\n\n"
                    f"{e('hourglass')} Taxminan <b>{minutes} daqiqa</b> "
                    "kutib, qayta /start yuboring."
                )
                return

            user.locked_until = None
            user.failed_attempts = 0

        if _password_matches(raw_password):
            user.is_authenticated = True
            user.failed_attempts = 0
            user.locked_until = None
            user.last_authenticated_at = now

            await session.commit()
            await state.clear()
            await message.answer(AUTH_SUCCESS_TEXT)
            return

        user.is_authenticated = False
        user.failed_attempts = (user.failed_attempts or 0) + 1
        attempts = user.failed_attempts

        if attempts >= MAX_PASSWORD_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)

            await session.commit()
            await state.clear()
            await message.answer(
                f"{e('cross')} <b>Kirish vaqtincha bloklandi.</b>\n\n"
                f"{MAX_PASSWORD_ATTEMPTS} marta noto'g'ri parol kiritildi.\n"
                f"{e('hourglass')} {LOCKOUT_MINUTES} daqiqadan keyin "
                "qayta urinib ko'ring."
            )
            return

        await session.commit()

    await message.answer(
        f"{e('cross')} <b>Parol noto'g'ri.</b>\n\n"
        f"{e('key')} Qolgan urinishlar: <b>{MAX_PASSWORD_ATTEMPTS - attempts}</b>\n"
        f"{CANCEL_HINT}"
    )


# ================================================================
# KO'RISH KOMANDALARI
# ================================================================

@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if not await require_admin(message):
        return

    await message.answer(HELP_TEXT)


@router.message(Command("birthdays"))
async def birthdays_command(message: Message) -> None:
    if not await require_admin(message):
        return

    async with SessionLocal() as session:
        people = await list_people(session)

    if not people:
        await message.answer(
            f"{e('mailbox')} <b>Hozircha faol tug'ilgan kunlar yo'q.</b>\n"
            f"{e('plus')} Yangi inson qo'shish: /add"
        )
        return

    await _send_long_text(message, birthday_table(people, local_today()))


@router.message(Command("today"))
async def today_command(message: Message) -> None:
    if not await require_admin(message):
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session)

    found = [
        person
        for person in people
        if birthday_date_for_year(person.birth_date, today.year) == today
    ]

    if not found:
        await message.answer(
            card(
                title("party", "Bugungi tug'ilgan kunlar"),
                f"{e('calendar')} {format_date_uz(today)}\n"
                f"Bugun tug'ilgan kuni bo'lgan inson yo'q. {e('yellow_heart')}",
            )
        )
        return

    entries = "\n".join(
        f"{e('cake')} <b>{safe(person.full_name)}</b> — "
        f"{age_on(person.birth_date, today)} yosh  <code>#{person.id}</code>"
        for person in found
    )

    await _send_long_text(
        message,
        card(
            title("party", "Bugungi tug'ilgan kunlar"),
            f"{e('calendar')} {format_date_uz(today)}",
            entries,
            hint("Test tabrik: /testbirthday ID"),
        ),
    )


@router.message(Command("next"))
async def next_command(message: Message) -> None:
    if not await require_admin(message):
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session)

    if not people:
        await message.answer(
            f"{e('mailbox')} Bazada faol insonlar yo'q. Qo'shish: /add"
        )
        return

    person = sort_by_upcoming(people, today)[0]
    remaining = days_until(person.birth_date, today)

    if remaining == 0:
        countdown = f"{e('party')} <b>Bugun tug'ilgan kuni!</b>"
    elif remaining == 1:
        countdown = f"{e('bell')} <b>Ertaga!</b>"
    else:
        countdown = f"{e('hourglass')} <b>{remaining} kun</b> qoldi"

    await message.answer(
        card(
            title("cake", "Eng yaqin tug'ilgan kun"),
            row("person", "Ism", f"<b>{safe(person.full_name)}</b>")
            + "\n"
            + row("calendar", "Sana", format_date_uz(person.birth_date))
            + "\n"
            + row(
                "balloon",
                "Yosh",
                f"<b>{turning_age(person.birth_date, today)}</b> yosh bo'ladi",
            ),
            countdown,
        )
    )


@router.message(Command("upcoming"))
async def upcoming_command(message: Message) -> None:
    if not await require_admin(message):
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session)

    found = [
        person
        for person in people
        if days_until(person.birth_date, today) <= UPCOMING_DAYS
    ]

    if not found:
        await message.answer(
            card(
                title("bell", f"Keyingi {UPCOMING_DAYS} kun"),
                "Ushbu davr ichida tug'ilgan kun yo'q.",
            )
        )
        return

    await _send_long_text(
        message,
        birthday_table(found, today, heading=f"KEYINGI {UPCOMING_DAYS} KUN"),
    )


# ================================================================
# QO'SHISH
# ================================================================

@router.message(Command("add"))
async def add_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    await state.clear()
    await state.set_state(AddStates.name)

    await message.answer(
        card(
            title("plus", "Yangi inson qo'shish"),
            f"{e('pencil')} <b>1/2</b> · To'liq ismni kiriting.\n"
            f"{hint('Masalan: Ali Valiyev')}",
            CANCEL_HINT,
        )
    )


@router.message(AddStates.name, F.text)
async def add_name(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    name = " ".join((message.text or "").split())

    if name.startswith("/"):
        await message.answer(
            f"{e('pencil')} Iltimos, komanda emas, insonning to'liq ismini kiriting."
        )
        return

    if not 2 <= len(name) <= MAX_NAME_LENGTH:
        await message.answer(
            f"{e('warning')} Ism uzunligi 2–{MAX_NAME_LENGTH} belgi "
            "oralig'ida bo'lishi kerak."
        )
        return

    await state.update_data(full_name=name)
    await state.set_state(AddStates.birth_date)

    await message.answer(
        f"{e('calendar')} <b>2/2</b> · Tug'ilgan sanani "
        "<code>DD.MM.YYYY</code> formatida yuboring.\n"
        f"{hint('Masalan:')} <code>25.10.2005</code>"
    )


@router.message(AddStates.birth_date, F.text)
async def add_birth_date(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    raw_date = (message.text or "").strip()
    birth_date = None if raw_date.startswith("/") else _parse_birth_date(raw_date)

    if birth_date is None:
        await message.answer(
            f"{e('cross')} <b>Sana noto'g'ri.</b>\n"
            "Format: <code>DD.MM.YYYY</code>\n"
            + hint("Sana 1900-yildan keyin va bugundan kech bo'lmasligi kerak.")
        )
        return

    data = await state.get_data()
    full_name = data.get("full_name")

    if not full_name:
        await state.clear()
        await message.answer(
            f"{e('warning')} Jarayon holati yo'qolgan. Qayta /add yuboring."
        )
        return

    async with SessionLocal() as session:
        person = Person(full_name=full_name, birth_date=birth_date)
        session.add(person)
        await session.commit()
        await session.refresh(person)
        person_id = person.id

    await state.clear()

    await message.answer(
        card(
            title("check", "Inson muvaffaqiyatli qo'shildi"),
            row("person", "Ism", f"<b>{safe(full_name)}</b>")
            + "\n"
            + row("calendar", "Tug'ilgan sana", format_date_uz(birth_date))
            + "\n"
            + row("key", "ID", f"<code>{person_id}</code>"),
            f"{e('picture')} Surat: <code>/setphoto {person_id}</code>\n"
            f"{e('music')} Musiqa: <code>/setmusic {person_id}</code>\n"
            f"{e('pencil')} Tahrirlash: <code>/edit {person_id}</code>",
        )
    )


# ================================================================
# TAHRIRLASH VA ARXIVLASH
# ================================================================

@router.message(Command("edit"))
async def edit_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("pencil", "/edit ID", "/edit 5"))
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)

        if person is None:
            await message.answer(_not_found_text())
            return

        current_name = person.full_name
        current_date = person.birth_date

    await state.clear()
    await state.update_data(edit_person_id=person_id)
    await state.set_state(EditStates.name)

    await message.answer(
        card(
            title("pencil", "Ma'lumotlarni tahrirlash"),
            row("person", "Joriy ism", f"<b>{safe(current_name)}</b>")
            + "\n"
            + row("calendar", "Joriy sana", f"<code>{current_date:%d.%m.%Y}</code>"),
            "Yangi ismni yuboring yoki o'zgartirmaslik uchun "
            "<code>-</code> kiriting.",
            CANCEL_HINT,
        )
    )


@router.message(EditStates.name, F.text)
async def edit_name(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    value = " ".join((message.text or "").split())

    if value.startswith("/"):
        await message.answer("Ismni kiriting yoki /cancel yuboring.")
        return

    if value != "-" and not 2 <= len(value) <= MAX_NAME_LENGTH:
        await message.answer(
            f"{e('warning')} Ism 2–{MAX_NAME_LENGTH} belgi oralig'ida bo'lishi kerak."
        )
        return

    await state.update_data(new_full_name=None if value == "-" else value)
    await state.set_state(EditStates.birth_date)

    await message.answer(
        f"{e('calendar')} Yangi tug'ilgan sanani <code>DD.MM.YYYY</code> "
        "formatida kiriting.\n"
        "O'zgartirmaslik uchun <code>-</code> yuboring."
    )


@router.message(EditStates.birth_date, F.text)
async def edit_birth_date(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    value = (message.text or "").strip()

    if value.startswith("/"):
        await message.answer("Sanani kiriting yoki /cancel yuboring.")
        return

    new_date = None

    if value != "-":
        new_date = _parse_birth_date(value)

        if new_date is None:
            await message.answer(
                f"{e('cross')} Sana noto'g'ri. "
                "<code>DD.MM.YYYY</code> formatidan foydalaning."
            )
            return

    data = await state.get_data()
    person_id = data.get("edit_person_id")
    new_name = data.get("new_full_name")

    async with SessionLocal() as session:
        person = await _get_active_person(session, int(person_id or 0))

        if person is None:
            await state.clear()
            await message.answer(_not_found_text())
            return

        if new_name is not None:
            person.full_name = new_name

        if new_date is not None:
            person.birth_date = new_date

        await session.commit()

        final_name = person.full_name
        final_date = person.birth_date

    await state.clear()

    await message.answer(
        card(
            title("check", "Ma'lumotlar yangilandi"),
            row("person", "Ism", f"<b>{safe(final_name)}</b>")
            + "\n"
            + row("calendar", "Tug'ilgan sana", format_date_uz(final_date)),
        )
    )


@router.message(Command("delete"))
async def delete_person(message: Message) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("folder", "/delete ID", "/delete 5"))
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)

        if person is None:
            await message.answer(_not_found_text())
            return

        person.is_active = False
        await session.commit()
        name = person.full_name

    await message.answer(
        card(
            title("folder", "Inson arxivlandi"),
            row("person", "Ism", f"<b>{safe(name)}</b>"),
            hint("U faol ro'yxat va kelgusi eslatmalarda qatnashmaydi."),
        )
    )


# ================================================================
# MEDIA
# ================================================================

@router.message(Command("setphoto"))
async def set_photo_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("picture", "/setphoto ID", "/setphoto 5"))
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)

        if person is None:
            await message.answer(_not_found_text())
            return

        name = person.full_name

    await state.clear()
    await state.update_data(media_person_id=person_id)
    await state.set_state(MediaStates.waiting_photo)

    await message.answer(
        f"{e('picture')} <b>{safe(name)}</b> uchun surat yuboring.\n\n"
        f"{CANCEL_HINT}"
    )


@router.message(MediaStates.waiting_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    data = await state.get_data()
    person_id = data.get("media_person_id")

    if not person_id:
        await state.clear()
        await message.answer(
            f"{e('warning')} Yuklash sessiyasi topilmadi. Qayta urinib ko'ring."
        )
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, int(person_id))

        if person is None:
            await state.clear()
            await message.answer(_not_found_text())
            return

        person.photo_file_id = message.photo[-1].file_id
        await session.commit()
        name = person.full_name

    await state.clear()

    await message.answer(
        f"{e('check')} <b>Surat saqlandi.</b>\n"
        f"{e('person')} Inson: <b>{safe(name)}</b>"
    )


@router.message(MediaStates.waiting_photo)
async def invalid_photo_input(message: Message) -> None:
    if not await require_admin(message):
        return

    await message.answer(
        f"{e('warning')} Iltimos, rasmni Telegram <b>photo</b> sifatida yuboring.\n"
        f"{CANCEL_HINT}"
    )


@router.message(Command("setmusic"))
async def set_music_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("music", "/setmusic ID", "/setmusic 5"))
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)

        if person is None:
            await message.answer(_not_found_text())
            return

        name = person.full_name

    await state.clear()
    await state.update_data(media_person_id=person_id)
    await state.set_state(MediaStates.waiting_audio)

    await message.answer(
        f"{e('music')} <b>{safe(name)}</b> uchun audio yuboring.\n"
        f"{hint('Audio yoki audio formatdagi hujjat (20 MB gacha).')}\n\n"
        f"{CANCEL_HINT}"
    )


@router.message(MediaStates.waiting_audio, F.audio | F.document)
async def receive_audio(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    file_id = None
    file_size = None

    if message.audio:
        file_id = message.audio.file_id
        file_size = message.audio.file_size

    elif message.document:
        document = message.document
        mime_type = (document.mime_type or "").lower()
        guessed_type = mimetypes.guess_type((document.file_name or "").lower())[0] or ""

        if not (mime_type.startswith("audio/") or guessed_type.startswith("audio/")):
            await message.answer(
                f"{e('warning')} Bu hujjat audio fayl emas. Audio fayl yuboring."
            )
            return

        file_id = document.file_id
        file_size = document.file_size

    if not file_id:
        await message.answer(f"{e('cross')} Audio faylni aniqlab bo'lmadi.")
        return

    if file_size is not None and file_size > MAX_AUDIO_SIZE:
        await message.answer(
            f"{e('warning')} Audio hajmi 20 MB dan oshmasligi kerak."
        )
        return

    data = await state.get_data()
    person_id = data.get("media_person_id")

    if not person_id:
        await state.clear()
        await message.answer(
            f"{e('warning')} Yuklash sessiyasi topilmadi. Qayta urinib ko'ring."
        )
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, int(person_id))

        if person is None:
            await state.clear()
            await message.answer(_not_found_text())
            return

        person.music_file_id = file_id
        await session.commit()
        name = person.full_name

    await state.clear()

    await message.answer(
        f"{e('check')} <b>Musiqa saqlandi.</b>\n"
        f"{e('person')} Inson: <b>{safe(name)}</b>"
    )


@router.message(MediaStates.waiting_audio)
async def invalid_audio_input(message: Message) -> None:
    if not await require_admin(message):
        return

    await message.answer(
        f"{e('warning')} Iltimos, audio yoki audio formatdagi hujjat yuboring.\n"
        f"{CANCEL_HINT}"
    )


# ================================================================
# GURUHLAR
# ================================================================

@router.message(Command("chatid"))
async def get_chat_id(message: Message) -> None:
    if not message.from_user:
        return

    if message.from_user.id not in settings.admin_ids:
        await message.answer(
            f"{e('cross')} Ushbu komanda faqat administrator uchun."
        )
        return

    await message.answer(
        card(
            title("search", "Telegram chat ma'lumotlari"),
            row("people", "Nomi", f"<b>{safe(message.chat.title or 'Shaxsiy chat')}</b>")
            + "\n"
            + row("key", "Chat ID", f"<code>{message.chat.id}</code>")
            + "\n"
            + row("folder", "Turi", f"<code>{message.chat.type}</code>"),
        )
    )


@router.message(Command("setgroup"))
async def set_group(message: Message) -> None:
    if not message.from_user:
        return

    if message.from_user.id not in settings.admin_ids:
        await message.answer(f"{e('cross')} Ushbu amal faqat administrator uchun.")
        return

    if message.chat.type == "private":
        if not await require_admin(message):
            return

        await message.answer(
            card(
                title("family", "Guruhni ulash"),
                "1. Botni oilaviy guruhga qo'shing.\n"
                "2. Botga xabar yuborish ruxsatini bering.\n"
                "3. O'sha guruh ichida /setgroup yuboring.",
            )
        )
        return

    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(
            f"{e('warning')} Bu komanda faqat Telegram guruhida ishlaydi."
        )
        return

    if not await authorized(message.from_user.id):
        await message.answer(
            f"{e('lock')} Avval bot bilan shaxsiy chatda /start orqali "
            "avtorizatsiyadan o'ting."
        )
        return

    chat_id = message.chat.id
    chat_title = (message.chat.title or "Family group")[:255]

    async with SessionLocal() as session:
        # Bitta asosiy guruh: eski guruh ID'lari bazadan o'chiriladi,
        # aks holda tabriklar eski guruhlarga ham yuborilaverardi.
        removed = await session.scalars(
            select(GroupConfig.chat_id).where(GroupConfig.chat_id != chat_id)
        )
        removed_ids = list(removed.all())

        await session.execute(
            delete(GroupConfig).where(GroupConfig.chat_id != chat_id)
        )

        cfg = await session.scalar(
            select(GroupConfig).where(GroupConfig.chat_id == chat_id)
        )

        if cfg is None:
            cfg = GroupConfig(chat_id=chat_id)
            session.add(cfg)

        cfg.title = chat_title
        cfg.timezone = settings.timezone
        cfg.reminder_time = settings.birthday_reminder_time
        cfg.is_active = True

        await session.commit()

    logger.info("Asosiy guruh: %s, o'chirilganlar: %s", chat_id, removed_ids)

    removed_text = ""

    if removed_ids:
        removed_text = f"{e('folder')} Eski guruhlar o'chirildi: " + ", ".join(
            f"<code>{item}</code>" for item in removed_ids
        )

    env_hint = ""

    if settings.target_group_id and settings.target_group_id != chat_id:
        env_hint = hint(
            f"Eslatma: .env dagi TARGET_GROUP_ID ({settings.target_group_id}) "
            f"ni {chat_id} ga almashtirishni unutmang."
        )

    await message.answer(
        card(
            title("check", "Guruh asosiy guruh sifatida saqlandi"),
            row("family", "Guruh", f"<b>{safe(chat_title)}</b>")
            + "\n"
            + row("key", "Chat ID", f"<code>{chat_id}</code>")
            + "\n"
            + row("alarm", "Eslatma vaqti", f"<code>{settings.birthday_reminder_time}</code>")
            + "\n"
            + row("globe", "Vaqt zonasi", f"<code>{safe(settings.timezone)}</code>"),
            removed_text,
            env_hint,
        )
    )


@router.message(F.migrate_to_chat_id)
async def group_migrated(message: Message) -> None:
    """Oddiy guruh superguruhga aylanganda chat ID avtomatik yangilanadi."""

    await migrate_group_chat_id(message.chat.id, message.migrate_to_chat_id)


@router.message(Command("groups"))
async def groups_command(message: Message) -> None:
    if not await require_admin(message):
        return

    async with SessionLocal() as session:
        groups = await get_active_groups(session)

    if not groups:
        await message.answer(
            card(
                title("family", "Ulangan guruhlar"),
                f"{e('warning')} Hech qanday guruh ulanmagan.\n"
                "Oilaviy guruh ichida /setgroup yuboring.",
            )
        )
        return

    entries = "\n\n".join(
        f"{e('family')} <b>{safe(group.title)}</b>\n"
        f"{e('key')} <code>{group.chat_id}</code>\n"
        f"{e('alarm')} {group.reminder_time} · {safe(group.timezone)}"
        for group in groups
    )

    await message.answer(card(title("family", "Ulangan guruhlar"), entries))


# ================================================================
# TEST VA HOLAT
# ================================================================

@router.message(Command("testbirthday"))
async def test_birthday(message: Message, bot: Bot) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("party", "/testbirthday ID", "/testbirthday 5"))
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)

        if person is None:
            await message.answer(_not_found_text())
            return

        person_data = PersonData.from_person(person)
        groups = await get_active_groups(session)

    if not groups:
        await message.answer(
            f"{e('warning')} <b>Eslatma guruhi sozlanmagan.</b>\n\n"
            "Oilaviy guruh ichida /setgroup yuboring yoki "
            "<code>TARGET_GROUP_ID</code> ni belgilang."
        )
        return

    await message.answer(
        f"{e('rocket')} <b>Test tabrigi yuborilmoqda...</b>\n"
        f"{e('person')} {safe(person_data.full_name)} · "
        f"{e('people')} {len(groups)} ta guruh"
    )

    results = [
        await send_birthday_greeting(bot, group.chat_id, person_data, local_today())
        for group in groups
    ]

    successful = sum(1 for result in results if result.greeting_sent)

    lines = []

    for index, result in enumerate(results, start=1):
        status = (
            f"{e('check')} Tabrik yuborildi"
            if result.greeting_sent
            else f"{e('cross')} Tabrik yuborilmadi"
        )
        line = f"<b>{index}.</b> <code>{result.chat_id}</code>\n{status}"

        if result.music_sent:
            line += f"\n{e('music')} Musiqa yuborildi"
        elif person_data.music_file_id and result.greeting_sent:
            line += f"\n{e('warning')} Musiqa yuborilmadi"

        if result.error:
            line += f"\n{e('warning')} <code>{safe(result.error[:250])}</code>"

        if result.music_error:
            line += f"\n{e('music')} <code>{safe(result.music_error[:250])}</code>"

        lines.append(line)

    await _send_long_text(
        message,
        card(
            title("sparkles", "Test natijasi"),
            row("person", "Inson", f"<b>{safe(person_data.full_name)}</b>")
            + "\n"
            + row("check", "Muvaffaqiyatli", f"<b>{successful}</b>")
            + "\n"
            + row("cross", "Xatolik", f"<b>{len(results) - successful}</b>"),
            DIVIDER,
            "\n\n".join(lines),
        ),
    )


@router.message(Command("status"))
async def status_command(message: Message) -> None:
    if not await require_admin(message):
        return

    try:
        async with SessionLocal() as session:
            active_count = len(await list_people(session))
            groups = await get_active_groups(session)

    except Exception:
        logger.exception("Ma'lumotlar bazasi holatini tekshirishda xato")
        await message.answer(
            card(
                title("chart", "Bot holati"),
                f"{e('check')} Bot: ishlayapti\n"
                f"{e('cross')} Ma'lumotlar bazasi: ulanishda xatolik",
            )
        )
        return

    await message.answer(
        card(
            title("chart", "Bot holati"),
            f"{e('check')} Bot: ishlayapti\n"
            f"{e('check')} Ma'lumotlar bazasi: ulandi",
            row("people", "Faol insonlar", f"<b>{active_count}</b>")
            + "\n"
            + row("family", "Faol guruhlar", f"<b>{len(groups)}</b>")
            + "\n"
            + row("alarm", "Eslatma vaqti", f"<code>{settings.birthday_reminder_time}</code>")
            + "\n"
            + row("globe", "Vaqt zonasi", f"<code>{safe(settings.timezone)}</code>"),
        )
    )
