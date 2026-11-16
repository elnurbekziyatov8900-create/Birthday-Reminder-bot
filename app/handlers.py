from __future__ import annotations

import logging
import mimetypes
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AuthUser, GroupConfig, Person
from app.services import (
    age_on,
    birthday_date_for_year,
    birthday_table,
    days_until,
    list_people,
    local_today,
    make_greeting,
)

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()

MAX_PASSWORD_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
MAX_NAME_LENGTH = 200
MAX_AUDIO_SIZE = 20 * 1024 * 1024  # 20 MB
TELEGRAM_CAPTION_LIMIT = 1024

# ============================================================================
# PREMIUM TELEGRAM CUSTOM EMOJI
# ============================================================================

PREMIUM_PARTY_EMOJI = (
    '<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji>'
)
# ============================================================================
# FSM STATES
# ============================================================================

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


# ============================================================================
# TEXTS
# ============================================================================

WELCOME_TEXT = (
    "🎂 <b>Family Birthday Assistant</b>\n\n"
    "Assalomu alaykum! 👋\n\n"
    "Oilangiz uchun muhim sanalarni eslab qolish endi oson.\n\n"
    "🔐 Davom etish uchun kirish parolini yuboring.\n"
    "Bekor qilish uchun /cancel."
)

AUTH_SUCCESS_TEXT = (
    "✅ <b>Avtorizatsiya muvaffaqiyatli yakunlandi!</b>\n\n"
    "Family Birthday Assistant xizmatiga xush kelibsiz.\n\n"
    "📋 /help — barcha komandalar\n"
    "🎂 /birthdays — barcha tug‘ilgan kunlar\n"
    "🎉 /today — bugungi tug‘ilgan kunlar\n"
    "⏳ /next — eng yaqin tug‘ilgan kun\n"
    "📅 /upcoming — keyingi 30 kun\n"
    "➕ /add — yangi inson qo‘shish\n"
    "📊 /status — tizim holati"
)

HELP_TEXT = (
    "🎂 <b>Family Birthday Assistant</b>\n"
    "<i>Boshqaruv qo‘llanmasi</i>\n\n"
    "📅 <b>TUG‘ILGAN KUNLAR</b>\n"
    "/birthdays — barcha faol tug‘ilgan kunlar\n"
    "/today — bugungi tug‘ilgan kunlar\n"
    "/next — navbatdagi tug‘ilgan kun\n"
    "/upcoming — keyingi 30 kun ichidagi sanalar\n\n"
    "👤 <b>MA’LUMOTLARNI BOSHQARISH</b>\n"
    "/add — yangi inson qo‘shish\n"
    "/edit ID — inson ma’lumotlarini tahrirlash\n"
    "/delete ID — insonni arxivlash\n"
    "/setphoto ID — surat biriktirish\n"
    "/setmusic ID — musiqa biriktirish\n\n"
    "👨‍👩‍👧‍👦 <b>GURUH VA TABRIKLAR</b>\n"
    "/setgroup — joriy guruhni eslatma guruhi qilish\n"
    "/testbirthday ID — test tabrigini yuborish\n\n"
    "⚙️ <b>TIZIM</b>\n"
    "/status — bot va ma’lumotlar bazasi holati\n"
    "/cancel — joriy amalni bekor qilish\n"
    "/help — ushbu qo‘llanma"
)


# ============================================================================
# GENERAL HELPERS
# ============================================================================

def _safe_name(value: str) -> str:
    return escape(value, quote=True)


def _parse_person_id(message: Message, command: str) -> int | None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def _parse_birth_date(raw_value: str) -> date | None:
    try:
        parsed = datetime.strptime(raw_value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None

    if parsed.year < 1900 or parsed > local_today():
        return None

    return parsed


def _normalize_datetime(value: datetime) -> datetime:
    """DB'dan kelgan naive datetime qiymatini UTC deb talqin qiladi."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_private_admin(message: Message) -> bool:
    return (
        message.chat.type == "private"
        and message.from_user is not None
        and message.from_user.id in settings.admin_ids
    )


async def is_admin_id(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def authorized(user_id: int) -> bool:
    if user_id not in settings.admin_ids:
        return False

    async with SessionLocal() as session:
        user = await session.scalar(
            select(AuthUser).where(AuthUser.telegram_user_id == user_id)
        )
        return bool(user and user.is_authenticated)


async def require_admin(message: Message) -> bool:
    """Admin huquqi va shaxsiy avtorizatsiyani tekshiradi."""
    if message.chat.type != "private":
        await message.answer(
            "🔒 <b>Bu komanda shaxsiy chatda boshqariladi.</b>\n\n"
            "Bot bilan shaxsiy chatga o‘ting va /start yuboring.",
            parse_mode="HTML",
        )
        return False

    if not message.from_user or message.from_user.id not in settings.admin_ids:
        await message.answer(
            "⛔ <b>Kirishga ruxsat yo‘q.</b>",
            parse_mode="HTML",
        )
        return False

    if not await authorized(message.from_user.id):
        await message.answer(
            "🔐 Avval avtorizatsiyadan o‘ting: /start",
            parse_mode="HTML",
        )
        return False

    return True


async def _get_active_person(session: Any, person_id: int) -> Person | None:
    person = await session.get(Person, person_id)
    if person is None or not person.is_active:
        return None
    return person


async def _send_long_text(message: Message, text: str) -> None:
    """Telegram matn limitidan oshgan javoblarni xavfsiz bo‘lib yuboradi."""
    limit = 4000
    if len(text) <= limit:
        await message.answer(text, parse_mode="HTML")
        return

    remaining = text
    while remaining:
        chunk = remaining[:limit]
        split_at = chunk.rfind("\n")
        if split_at > limit // 2:
            chunk = chunk[:split_at]
        await message.answer(chunk, parse_mode="HTML")
        remaining = remaining[len(chunk):].lstrip("\n")


# ============================================================================
# CANCEL — FSM handlerlardan oldin ro‘yxatdan o‘tkaziladi
# ============================================================================

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    await state.clear()

    if current_state is None:
        response = "ℹ️ Hozir bekor qilinadigan faol jarayon mavjud emas."
    else:
        response = (
            "↩️ <b>Joriy jarayon bekor qilindi.</b>\n\n"
            "Davom etish uchun /help komandasidan foydalaning."
        )

    await message.answer(response, parse_mode="HTML")


# ============================================================================
# AUTHENTICATION
# ============================================================================

@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer(
            "🔐 Iltimos, botni shaxsiy chatda ochib, /start yuboring."
        )
        return

    if not message.from_user:
        return

    user_id = message.from_user.id
    if user_id not in settings.admin_ids:
        await state.clear()
        await message.answer(
            "⛔ <b>Kirishga ruxsat yo‘q.</b>\n\n"
            "Ushbu bot faqat ruxsat berilgan administrator uchun mo‘ljallangan.",
            parse_mode="HTML",
        )
        return

    if await authorized(user_id):
        await state.clear()
        await message.answer(
            "🎂 <b>Family Birthday Assistant</b>\n\n"
            "Qayta xush kelibsiz! Bot ishlashga tayyor.\n\n"
            "📋 Komandalar: /help\n"
            "📅 Yaqin sanalar: /upcoming",
            parse_mode="HTML",
        )
        return

    await state.set_state(AuthStates.waiting_password)
    await message.answer(WELCOME_TEXT, parse_mode="HTML")


@router.message(AuthStates.waiting_password, F.text)
async def password_input(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id not in settings.admin_ids:
        await state.clear()
        return

    raw_password = (message.text or "").strip()

    # Maxfiy parol Telegram chat tarixida qolmasligi uchun o‘chirishga urinamiz.
    try:
        await message.delete()
    except TelegramAPIError:
        logger.debug("Parol xabarini o‘chirish imkoni bo‘lmadi.")

    if raw_password.startswith("/"):
        await message.answer(
            "🔐 <b>Parol kutilmoqda.</b>\n"
            "Parolni yuboring yoki /cancel orqali jarayonni bekor qiling.",
            parse_mode="HTML",
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
        if user.locked_until and _normalize_datetime(user.locked_until) > now:
            remaining = _normalize_datetime(user.locked_until) - now
            minutes = max(1, (int(remaining.total_seconds()) + 59) // 60)
            await message.answer(
                "🔒 <b>Kirish vaqtincha bloklangan.</b>\n\n"
                f"Qayta urinish uchun taxminan <b>{minutes} daqiqa</b> kuting.",
                parse_mode="HTML",
            )
            return

        # Muddati tugagan blokni tozalash.
        if user.locked_until:
            user.locked_until = None
            user.failed_attempts = 0

        if raw_password == settings.bot_access_password:
            user.is_authenticated = True
            user.failed_attempts = 0
            user.locked_until = None
            user.last_authenticated_at = now
            await session.commit()
            await state.clear()
            await message.answer(AUTH_SUCCESS_TEXT, parse_mode="HTML")
            return

        user.is_authenticated = False
        user.failed_attempts = (user.failed_attempts or 0) + 1
        attempts = user.failed_attempts

        if attempts >= MAX_PASSWORD_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            await session.commit()
            await state.clear()
            await message.answer(
                "🚫 <b>Kirish vaqtincha bloklandi.</b>\n\n"
                f"{MAX_PASSWORD_ATTEMPTS} marta noto‘g‘ri parol kiritildi.\n"
                f"⏳ {LOCKOUT_MINUTES} daqiqadan keyin qayta urinishingiz mumkin.",
                parse_mode="HTML",
            )
            return

        await session.commit()
        left = MAX_PASSWORD_ATTEMPTS - attempts
        await message.answer(
            "❌ <b>Parol noto‘g‘ri.</b>\n\n"
            f"Qolgan urinishlar: <b>{left}</b>\n"
            "Bekor qilish: /cancel",
            parse_mode="HTML",
        )


# ============================================================================
# HELP
# ============================================================================

@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if not await require_admin(message):
        return
    await message.answer(HELP_TEXT, parse_mode="HTML")


# ============================================================================
# BIRTHDAY QUERIES
# ============================================================================

@router.message(Command("birthdays"))
async def birthdays_command(message: Message) -> None:
    if not await require_admin(message):
        return

    async with SessionLocal() as session:
        people = await list_people(session)

    if not people:
        await message.answer(
            "📭 <b>Hozircha faol tug‘ilgan kunlar mavjud emas.</b>\n"
            "Yangi inson qo‘shish: /add",
            parse_mode="HTML",
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
        person for person in people
        if birthday_date_for_year(person.birth_date, today.year) == today
    ]

    if not found:
        await message.answer(
            "🎉 <b>Bugungi tug‘ilgan kunlar</b>\n\n"
            "Bugun bazada tug‘ilgan kuni bo‘lgan inson topilmadi. 💛",
            parse_mode="HTML",
        )
        return

    lines = ["🎉 <b>Bugungi tug‘ilgan kunlar</b>\n"]
    for person in found:
        lines.append(
            f"🎂 <b>{_safe_name(person.full_name)}</b> — "
            f"{age_on(person.birth_date, today)} yosh"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("next"))
async def next_command(message: Message) -> None:
    if not await require_admin(message):
        return

    today = local_today()
    async with SessionLocal() as session:
        people = await list_people(session)

    if not people:
        await message.answer(
            "📭 Bazada faol insonlar yo‘q. Yangi inson qo‘shish: /add"
        )
        return

    person = min(
        people,
        key=lambda item: (
            days_until(item.birth_date, today),
            item.full_name.casefold(),
        ),
    )
    remaining = days_until(person.birth_date, today)

    if remaining == 0:
        countdown = "🎉 Bugun tug‘ilgan kuni!"
    elif remaining == 1:
        countdown = "⏳ Ertaga!"
    else:
        countdown = f"⏳ {remaining} kun qoldi."

    await message.answer(
        "🎂 <b>Eng yaqin tug‘ilgan kun</b>\n\n"
        f"👤 Ism: <b>{_safe_name(person.full_name)}</b>\n"
        f"📅 Sana: <code>{person.birth_date:%d.%m.%Y}</code>\n"
        f"{countdown}",
        parse_mode="HTML",
    )


@router.message(Command("upcoming"))
async def upcoming_command(message: Message) -> None:
    if not await require_admin(message):
        return

    today = local_today()
    async with SessionLocal() as session:
        people = await list_people(session)

    found = sorted(
        (
            person for person in people
            if 0 <= days_until(person.birth_date, today) <= 30
        ),
        key=lambda person: (
            days_until(person.birth_date, today),
            person.full_name.casefold(),
        ),
    )

    if not found:
        await message.answer(
            "📅 <b>Keyingi 30 kun</b>\n\n"
            "Ushbu davr ichida tug‘ilgan kuni bo‘lgan inson topilmadi.",
            parse_mode="HTML",
        )
        return

    table = birthday_table(found, today)
    await _send_long_text(message, table)


# ============================================================================
# ADD PERSON
# ============================================================================

@router.message(Command("add"))
async def add_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    await state.clear()
    await state.set_state(AddStates.name)
    await message.answer(
        "➕ <b>Yangi inson qo‘shish</b>\n\n"
        "To‘liq ismni kiriting.\n"
        "Masalan: <i>Ali Valiyev</i>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@router.message(AddStates.name, F.text)
async def add_name(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    name = (message.text or "").strip()
    if name.startswith("/"):
        await message.answer(
            "✏️ Iltimos, komanda emas, insonning to‘liq ismini kiriting."
        )
        return

    if not 2 <= len(name) <= MAX_NAME_LENGTH:
        await message.answer(
            f"⚠️ Ism uzunligi 2–{MAX_NAME_LENGTH} belgi oralig‘ida bo‘lishi kerak."
        )
        return

    await state.update_data(full_name=name)
    await state.set_state(AddStates.birth_date)
    await message.answer(
        "📅 Tug‘ilgan sanani <code>DD.MM.YYYY</code> formatida yuboring.\n"
        "Masalan: <code>25.10.2005</code>",
        parse_mode="HTML",
    )


@router.message(AddStates.birth_date, F.text)
async def add_birth_date(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    raw_date = (message.text or "").strip()
    if raw_date.startswith("/"):
        await message.answer(
            "📅 Tug‘ilgan sanani <code>DD.MM.YYYY</code> formatida yuboring.",
            parse_mode="HTML",
        )
        return

    birth_date = _parse_birth_date(raw_date)
    if birth_date is None:
        await message.answer(
            "❌ Sana noto‘g‘ri.\n"
            "Format: <code>DD.MM.YYYY</code>\n"
            "Sana 1900-yildan keyin va bugundan kech bo‘lmasligi kerak.",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    full_name = data.get("full_name")
    if not full_name:
        await state.clear()
        await message.answer("⚠️ Jarayon holati yo‘qolgan. Qayta /add yuboring.")
        return

    async with SessionLocal() as session:
        person = Person(full_name=full_name, birth_date=birth_date)
        session.add(person)
        await session.commit()
        await session.refresh(person)
        person_id = person.id

    await state.clear()
    await message.answer(
        "✅ <b>Inson muvaffaqiyatli qo‘shildi.</b>\n\n"
        f"👤 Ism: <b>{_safe_name(full_name)}</b>\n"
        f"📅 Tug‘ilgan sana: <code>{birth_date:%d.%m.%Y}</code>\n"
        f"🆔 ID: <code>{person_id}</code>\n\n"
        f"🖼 Surat: <code>/setphoto {person_id}</code>\n"
        f"🎵 Musiqa: <code>/setmusic {person_id}</code>\n"
        f"✏️ Tahrirlash: <code>/edit {person_id}</code>",
        parse_mode="HTML",
    )


# ============================================================================
# EDIT PERSON
# ============================================================================

@router.message(Command("edit"))
async def edit_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message, "edit")
    if person_id is None:
        await message.answer(
            "✏️ Foydalanish: <code>/edit ID</code>\n"
            "Masalan: <code>/edit 5</code>",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)
        if person is None:
            await message.answer("❌ Bunday faol ID topilmadi.")
            return
        current_name = person.full_name
        current_date = person.birth_date

    await state.clear()
    await state.update_data(edit_person_id=person_id)
    await state.set_state(EditStates.name)
    await message.answer(
        "✏️ <b>Ma’lumotlarni tahrirlash</b>\n\n"
        f"Joriy ism: <b>{_safe_name(current_name)}</b>\n"
        "Yangi ismni yuboring yoki o‘zgartirmaslik uchun <code>-</code> kiriting.",
        parse_mode="HTML",
    )


@router.message(EditStates.name, F.text)
async def edit_name(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    value = (message.text or "").strip()
    if value.startswith("/"):
        await message.answer("Ismni kiriting yoki /cancel yuboring.")
        return
    if value != "-" and not 2 <= len(value) <= MAX_NAME_LENGTH:
        await message.answer(
            f"Ism 2–{MAX_NAME_LENGTH} belgi oralig‘ida bo‘lishi kerak."
        )
        return

    await state.update_data(new_full_name=None if value == "-" else value)
    await state.set_state(EditStates.birth_date)
    await message.answer(
        "📅 Yangi tug‘ilgan sanani <code>DD.MM.YYYY</code> formatida kiriting.\n"
        "O‘zgartirmaslik uchun <code>-</code> yuboring.",
        parse_mode="HTML",
    )


@router.message(EditStates.birth_date, F.text)
async def edit_birth_date(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    value = (message.text or "").strip()
    if value.startswith("/"):
        await message.answer("Sanani kiriting yoki /cancel yuboring.")
        return

    new_date: date | None = None
    if value != "-":
        new_date = _parse_birth_date(value)
        if new_date is None:
            await message.answer(
                "❌ Sana noto‘g‘ri. <code>DD.MM.YYYY</code> formatidan foydalaning.",
                parse_mode="HTML",
            )
            return

    data = await state.get_data()
    person_id = data.get("edit_person_id")
    new_name = data.get("new_full_name")

    async with SessionLocal() as session:
        person = await _get_active_person(session, int(person_id or 0))
        if person is None:
            await state.clear()
            await message.answer("❌ Inson topilmadi yoki arxivlangan.")
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
        "✅ <b>Ma’lumotlar yangilandi.</b>\n\n"
        f"👤 Ism: <b>{_safe_name(final_name)}</b>\n"
        f"📅 Tug‘ilgan sana: <code>{final_date:%d.%m.%Y}</code>",
        parse_mode="HTML",
    )


# ============================================================================
# ARCHIVE PERSON
# ============================================================================

@router.message(Command("delete"))
async def delete_person(message: Message) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message, "delete")
    if person_id is None:
        await message.answer(
            "🗑 Foydalanish: <code>/delete ID</code>\n"
            "Masalan: <code>/delete 5</code>",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)
        if person is None:
            await message.answer("❌ Bunday faol ID topilmadi.")
            return

        person.is_active = False
        await session.commit()
        name = person.full_name

    await message.answer(
        "✅ <b>Inson arxivlandi.</b>\n\n"
        f"👤 {_safe_name(name)}\n"
        "U faol ro‘yxat va kelgusi eslatmalarda qatnashmaydi.",
        parse_mode="HTML",
    )


# ============================================================================
# MEDIA ATTACHMENT
# ============================================================================

@router.message(Command("setphoto"))
async def set_photo_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message, "setphoto")
    if person_id is None:
        await message.answer(
            "🖼 Foydalanish: <code>/setphoto ID</code>",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)
        if person is None:
            await message.answer("❌ Faol inson topilmadi.")
            return
        name = person.full_name

    await state.clear()
    await state.update_data(media_person_id=person_id)
    await state.set_state(MediaStates.waiting_photo)
    await message.answer(
        f"🖼 <b>{_safe_name(name)}</b> uchun surat yuboring.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@router.message(MediaStates.waiting_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    data = await state.get_data()
    person_id = data.get("media_person_id")
    if not person_id:
        await state.clear()
        await message.answer("⚠️ Yuklash sessiyasi topilmadi. Qayta urinib ko‘ring.")
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, int(person_id))
        if person is None:
            await state.clear()
            await message.answer("❌ Inson topilmadi yoki arxivlangan.")
            return

        person.photo_file_id = message.photo[-1].file_id
        await session.commit()
        name = person.full_name

    await state.clear()
    await message.answer(
        "✅ <b>Surat muvaffaqiyatli saqlandi.</b>\n"
        f"👤 Inson: <b>{_safe_name(name)}</b>",
        parse_mode="HTML",
    )


@router.message(MediaStates.waiting_photo)
async def invalid_photo_input(message: Message) -> None:
    await message.answer(
        "⚠️ Iltimos, rasmni Telegram <b>photo</b> sifatida yuboring.\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@router.message(Command("setmusic"))
async def set_music_start(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message, "setmusic")
    if person_id is None:
        await message.answer(
            "🎵 Foydalanish: <code>/setmusic ID</code>",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)
        if person is None:
            await message.answer("❌ Faol inson topilmadi.")
            return
        name = person.full_name

    await state.clear()
    await state.update_data(media_person_id=person_id)
    await state.set_state(MediaStates.waiting_audio)
    await message.answer(
        f"🎵 <b>{_safe_name(name)}</b> uchun audio yuboring.\n\n"
        "Audio yoki audio formatdagi hujjat qabul qilinadi (20 MB gacha).\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@router.message(MediaStates.waiting_audio, F.audio | F.document)
async def receive_audio(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    file_id: str | None = None
    file_size: int | None = None

    if message.audio:
        file_id = message.audio.file_id
        file_size = message.audio.file_size
    elif message.document:
        document = message.document
        mime_type = (document.mime_type or "").lower()
        filename = (document.file_name or "").lower()
        guessed_type = mimetypes.guess_type(filename)[0] or ""
        if not (mime_type.startswith("audio/") or guessed_type.startswith("audio/")):
            await message.answer(
                "⚠️ Bu hujjat audio fayl emas. Audio formatdagi fayl yuboring."
            )
            return
        file_id = document.file_id
        file_size = document.file_size

    if not file_id:
        await message.answer("❌ Audio faylni aniqlab bo‘lmadi.")
        return

    if file_size and file_size > MAX_AUDIO_SIZE:
        await message.answer("⚠️ Audio hajmi 20 MB dan oshmasligi kerak.")
        return

    data = await state.get_data()
    person_id = data.get("media_person_id")
    if not person_id:
        await state.clear()
        await message.answer("⚠️ Yuklash sessiyasi topilmadi. Qayta urinib ko‘ring.")
        return

    async with SessionLocal() as session:
        person = await _get_active_person(session, int(person_id))
        if person is None:
            await state.clear()
            await message.answer("❌ Inson topilmadi yoki arxivlangan.")
            return

        person.music_file_id = file_id
        await session.commit()
        name = person.full_name

    await state.clear()
    await message.answer(
        "✅ <b>Musiqa muvaffaqiyatli saqlandi.</b>\n"
        f"👤 Inson: <b>{_safe_name(name)}</b>",
        parse_mode="HTML",
    )


@router.message(MediaStates.waiting_audio)
async def invalid_audio_input(message: Message) -> None:
    await message.answer(
        "⚠️ Iltimos, audio yoki audio formatdagi hujjat yuboring.\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )

# ============================================================================
# GET TELEGRAM CHAT ID
# ============================================================================

@router.message(Command("chatid"))
async def get_chat_id(message: Message) -> None:
    if not message.from_user:
        return

    if message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ Ushbu komanda faqat administrator uchun.")
        return

    chat_type = message.chat.type
    chat_id = message.chat.id
    chat_title = message.chat.title or "Private chat"

    await message.answer(
        "🔎 <b>TELEGRAM CHAT MA'LUMOTLARI</b>\n\n"
        f"👥 Nomi: <b>{_safe_name(chat_title)}</b>\n"
        f"🆔 Chat ID: <code>{chat_id}</code>\n"
        f"📌 Chat turi: <code>{chat_type}</code>",
        parse_mode="HTML",
    )

# ============================================================================
# GROUP CONFIGURATION
# ============================================================================

@router.message(Command("setgroup"))
async def set_group(message: Message) -> None:
    if not message.from_user or message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ Ushbu amal faqat administrator uchun.")
        return

    if message.chat.type == "private":
        if not await require_admin(message):
            return
        await message.answer(
            "👨‍👩‍👧‍👦 Avval botni oilaviy guruhga qo‘shing.\n"
            "So‘ngra o‘sha guruh ichida /setgroup yuboring."
        )
        return

    # Guruh ichida ham adminning DB avtorizatsiyasini tekshiramiz.
    if not await authorized(message.from_user.id):
        await message.answer(
            "🔐 Avval bot bilan shaxsiy chatda /start orqali avtorizatsiyadan o‘ting."
        )
        return

    chat_title = message.chat.title or "Family group"
    async with SessionLocal() as session:
        cfg = await session.scalar(
            select(GroupConfig).where(GroupConfig.chat_id == message.chat.id)
        )

        if cfg is None:
            cfg = GroupConfig(
                chat_id=message.chat.id,
                title=chat_title,
                timezone=settings.timezone,
                reminder_time=settings.birthday_reminder_time,
                is_active=True,
            )
            session.add(cfg)
        else:
            cfg.title = chat_title
            cfg.timezone = settings.timezone
            cfg.reminder_time = settings.birthday_reminder_time
            cfg.is_active = True

        await session.commit()

    await message.answer(
        "✅ <b>Guruh sozlamalari saqlandi.</b>\n\n"
        f"👨‍👩‍👧‍👦 Guruh: <b>{_safe_name(chat_title)}</b>\n"
        f"🕘 Eslatma vaqti: <code>{settings.birthday_reminder_time}</code>\n"
        f"🌍 Vaqt zonasi: <code>{_safe_name(settings.timezone)}</code>",
        parse_mode="HTML",
    )


# ============================================================================
# TEST BIRTHDAY NOTIFICATION — PREMIUM VERSION
# ============================================================================

@router.message(Command("testbirthday"))
async def test_birthday(message: Message, bot: Bot) -> None:
    if not await require_admin(message):
        return

    person_id = _parse_person_id(message, "testbirthday")

    if person_id is None:
        await message.answer(
            "🎉 Foydalanish: <code>/testbirthday ID</code>\n\n"
            "Masalan: <code>/testbirthday 5</code>",
            parse_mode="HTML",
        )
        return

    # 1. Ma'lumotlarni bazadan olish
    async with SessionLocal() as session:
        person = await _get_active_person(session, person_id)

        if person is None:
            await message.answer(
                "❌ <b>Inson topilmadi.</b>\n\n"
                "ID noto‘g‘ri yoki ushbu inson arxivlangan.",
                parse_mode="HTML",
            )
            return

        greeting = make_greeting(person, local_today())
        photo_file_id = person.photo_file_id
        music_file_id = person.music_file_id
        full_name = person.full_name

        group_id = settings.target_group_id

        if group_id is None:
            cfg = await session.scalar(
                select(GroupConfig)
                .where(GroupConfig.is_active.is_(True))
                .order_by(GroupConfig.id.asc())
            )
            group_id = cfg.chat_id if cfg else None

    # 2. Guruhni tekshirish
    if group_id is None:
        await message.answer(
            "⚠️ <b>Eslatma guruhi sozlanmagan.</b>\n\n"
            "Oilaviy guruh ichida /setgroup yuboring yoki "
            "<code>TARGET_GROUP_ID</code> sozlamasini belgilang.",
            parse_mode="HTML",
        )
        return

    premium_emoji_sent = False
    greeting_sent = False
    music_sent = False
    greeting_message_id = None

    try:
        # 3. Animatsiyali Premium Custom Emoji
        try:
            await bot.send_message(
                chat_id=group_id,
                text=PREMIUM_PARTY_EMOJI,
                parse_mode="HTML",
            )
            premium_emoji_sent = True

        except TelegramAPIError:
            logger.warning(
                "Premium Custom Emoji yuborilmadi. "
                "Asosiy tabrik davom ettiriladi.",
                exc_info=True,
            )

        # 4. Asosiy tabrik
        if photo_file_id:
            if len(greeting) <= TELEGRAM_CAPTION_LIMIT:
                sent = await bot.send_photo(
                    chat_id=group_id,
                    photo=photo_file_id,
                    caption=greeting,
                    parse_mode="HTML",
                )
            else:
                sent = await bot.send_photo(
                    chat_id=group_id,
                    photo=photo_file_id,
                )

                await _send_long_text_to_chat(
                    bot=bot,
                    chat_id=group_id,
                    text=greeting,
                )

            greeting_message_id = sent.message_id

        else:
            sent = await bot.send_message(
                chat_id=group_id,
                text=greeting,
                parse_mode="HTML",
            )
            greeting_message_id = sent.message_id

        greeting_sent = True

        # 5. Tabrik musiqasi
        if music_file_id:
            await bot.send_audio(
                chat_id=group_id,
                audio=music_file_id,
                caption=(
                    f"🎵 <b>{_safe_name(full_name)}</b> "
                    "uchun tabrik musiqasi"
                ),
                parse_mode="HTML",
            )
            music_sent = True

    except TelegramForbiddenError:
        logger.exception("Bot guruhga xabar yubora olmadi.")

        await message.answer(
            "❌ <b>Bot guruhga xabar yubora olmadi.</b>\n\n"
            "Bot guruhdan chiqarilgan yoki xabar yuborish "
            "huquqiga ega emas.",
            parse_mode="HTML",
        )
        return

    except TelegramBadRequest as exc:
        logger.exception("Test tabrigida Telegram BadRequest.")

        await message.answer(
            "❌ <b>Telegram xabarni qabul qilmadi.</b>\n\n"
            f"<code>{_safe_name(str(exc)[:500])}</code>",
            parse_mode="HTML",
        )
        return

    except TelegramAPIError:
        logger.exception("Test tabrigida Telegram API xatosi.")

        await message.answer(
            "❌ <b>Telegram API bilan bog‘liq xatolik yuz berdi.</b>\n\n"
            "Railway loglarini tekshiring.",
            parse_mode="HTML",
        )
        return

    # 6. Test natijasi
    premium_status = "🟢 Yuborildi" if premium_emoji_sent else "🟡 Yuborilmadi"
    greeting_status = "🟢 Yuborildi" if greeting_sent else "🔴 Yuborilmadi"
    music_status = "🟢 Yuborildi" if music_sent else "⚪ Biriktirilmagan"

    result = (
        "✨ <b>PREMIUM TEST YAKUNLANDI</b>\n\n"
        f"👤 Ism: <b>{_safe_name(full_name)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎉 Premium emoji: {premium_status}\n"
        f"🎂 Asosiy tabrik: {greeting_status}\n"
        f"🎵 Musiqa: {music_status}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Xabar ID: <code>{greeting_message_id}</code>"
    )

    await message.answer(result, parse_mode="HTML")

# ============================================================================
# STATUS
# ============================================================================

@router.message(Command("status"))
async def status_command(message: Message) -> None:
    if not await require_admin(message):
        return

    try:
        async with SessionLocal() as session:
            people = await list_people(session)
            active_count = len(people)
    except Exception:
        logger.exception("Ma’lumotlar bazasi holatini tekshirishda xato")
        await message.answer(
            "📊 <b>Bot holati</b>\n\n"
            "🟢 Bot: ishlayapti\n"
            "🔴 Ma’lumotlar bazasi: ulanishda xatolik",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "📊 <b>Bot holati</b>\n\n"
        "🟢 Bot: ishlayapti\n"
        "🟢 Ma’lumotlar bazasi: ulandi\n"
        f"👥 Faol insonlar: <b>{active_count}</b>\n"
        f"🕘 Eslatma vaqti: <code>{settings.birthday_reminder_time}</code>\n"
        f"🌍 Vaqt zonasi: <code>{_safe_name(settings.timezone)}</code>",
        parse_mode="HTML",
    )
