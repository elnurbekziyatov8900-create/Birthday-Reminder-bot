from __future__ import annotations

import hmac
import logging
import mimetypes
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.messaging import (
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
GROUP_CALLBACK_PREFIX = "grp:"


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
    f"{e('family')} /groups — guruhni tanlash\n"
    f"{e('calendar')} /birthdays — guruh jadvali\n"
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
    hint(
        "Har bir guruhning o'z oila jadvali bor. Tabrik faqat o'sha "
        "guruhga yuboriladi. Komandalar tanlangan guruh bilan ishlaydi."
    ),
    f"{e('family')} <b>GURUHLAR</b>\n"
    + quote(
        "/groups — guruhlar ro'yxati va guruhni tanlash\n"
        "/setgroup — (guruh ichida) guruhni ulash\n"
        "/removegroup — (guruh ichida) guruhni o'chirish\n"
        "/chatid — joriy chat ID sini ko'rish"
    ),
    f"{e('calendar')} <b>TUG'ILGAN KUNLAR</b>\n"
    + quote(
        "/birthdays — tanlangan guruh jadvali\n"
        "/today — bugungi tug'ilgan kunlar\n"
        "/next — navbatdagi tug'ilgan kun\n"
        f"/upcoming — keyingi {UPCOMING_DAYS} kun ichidagi sanalar"
    ),
    f"{e('person')} <b>JADVALNI BOSHQARISH</b>\n"
    + quote(
        "/add — guruh jadvaliga inson qo'shish\n"
        "/edit ID — ma'lumotlarni tahrirlash\n"
        "/delete ID — insonni arxivlash\n"
        "/assign ID — insonni tanlangan guruhga o'tkazish\n"
        "/setphoto ID — surat biriktirish\n"
        "/setmusic ID — musiqa biriktirish\n"
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


def _group_line(group: GroupConfig) -> str:
    return f"{e('family')} Guruh: <b>{safe(group.title)}</b>"


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


async def _active_groups(session: Any) -> list[GroupConfig]:
    result = await session.scalars(
        select(GroupConfig)
        .where(GroupConfig.is_active.is_(True))
        .order_by(GroupConfig.title.asc(), GroupConfig.id.asc())
    )

    return list(result.all())


async def _get_auth_user(session: Any, user_id: int) -> AuthUser | None:
    return await session.scalar(
        select(AuthUser).where(AuthUser.telegram_user_id == user_id)
    )


async def _selected_group(session: Any, user_id: int) -> GroupConfig | None:
    """Admin tanlagan guruh. Faqat bitta guruh bo'lsa — avtomatik o'sha."""

    user = await _get_auth_user(session, user_id)

    if user and user.selected_group_id:
        group = await session.get(GroupConfig, user.selected_group_id)

        if group is not None and group.is_active:
            return group

    groups = await _active_groups(session)

    if len(groups) == 1:
        if user is not None:
            user.selected_group_id = groups[0].id
            await session.commit()

        return groups[0]

    return None


def _groups_keyboard(
    groups: list[GroupConfig],
    selected_id: int | None,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if group.id == selected_id else "👨‍👩‍👧‍👦 ")
                    + group.title[:60],
                    callback_data=f"{GROUP_CALLBACK_PREFIX}{group.id}",
                )
            ]
            for group in groups
        ]
    )


async def _ask_to_choose_group(message: Message, session: Any) -> None:
    groups = await _active_groups(session)

    if not groups:
        await message.answer(
            card(
                title("family", "Guruh ulanmagan"),
                "1. Botni oilaviy guruhga qo'shing.\n"
                "2. Guruh ichida /setgroup yuboring.",
            )
        )
        return

    await message.answer(
        card(
            title("family", "Avval guruhni tanlang"),
            "Qaysi oila jadvali bilan ishlaymiz?",
        ),
        reply_markup=_groups_keyboard(groups, None),
    )


async def _admin_group(message: Message) -> GroupConfig | None:
    """Shaxsiy chatdagi boshqaruv komandalari uchun: admin + tanlangan guruh."""

    if not await require_admin(message):
        return None

    async with SessionLocal() as session:
        group = await _selected_group(session, message.from_user.id)

        if group is None:
            await _ask_to_choose_group(message, session)

        return group


async def _view_group(message: Message) -> GroupConfig | None:
    """Ko'rish komandalari: shaxsiy chatda — tanlangan guruh, guruh ichida
    esa aynan shu guruhning jadvali (faqat avtorizatsiyadan o'tgan admin)."""

    if message.chat.type == "private":
        return await _admin_group(message)

    if not message.from_user or not await authorized(message.from_user.id):
        return None

    async with SessionLocal() as session:
        group = await session.scalar(
            select(GroupConfig).where(
                GroupConfig.chat_id == message.chat.id,
                GroupConfig.is_active.is_(True),
            )
        )

    if group is None:
        await message.answer(
            f"{e('warning')} Bu guruh hali ulanmagan. Ulash uchun /setgroup yuboring."
        )

    return group


async def _get_person(
    session: Any,
    person_id: int,
    group_id: int | None,
) -> Person | None:
    """Faol inson. ``group_id`` berilsa, inson shu guruhga tegishli bo'lishi shart."""

    person = await session.get(Person, person_id)

    if person is None or not person.is_active:
        return None

    if group_id is not None and person.group_id != group_id:
        return None

    return person


async def _send_long_text(message: Message, text: str) -> None:
    for chunk in split_html_text(text):
        await message.answer(chunk)


def _not_found_text(group: GroupConfig | None = None) -> str:
    where = (
        f" <b>{safe(group.title)}</b> guruhi jadvalida" if group is not None else ""
    )

    return (
        f"{e('cross')} <b>Inson topilmadi.</b>\n"
        f"Bunday ID{where} yo'q yoki inson arxivlangan.\n"
        + hint("Ro'yxat: /birthdays · Guruhni almashtirish: /groups")
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
            "Parolni yuboring yoki /cancel orqali bekor qiling."
        )
        return

    async with SessionLocal() as session:
        user = await _get_auth_user(session, message.from_user.id)

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


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if not await require_admin(message):
        return

    await message.answer(HELP_TEXT)


# ================================================================
# GURUHLAR
# ================================================================

@router.message(Command("groups"))
async def groups_command(message: Message) -> None:
    if not await require_admin(message):
        return

    async with SessionLocal() as session:
        groups = await _active_groups(session)
        selected = await _selected_group(session, message.from_user.id)

        counts = dict(
            (
                await session.execute(
                    select(Person.group_id, func.count(Person.id))
                    .where(Person.is_active.is_(True))
                    .group_by(Person.group_id)
                )
            ).all()
        )

    if not groups:
        await message.answer(
            card(
                title("family", "Ulangan guruhlar"),
                f"{e('warning')} Hech qanday guruh ulanmagan.\n"
                "Botni guruhga qo'shib, guruh ichida /setgroup yuboring.",
            )
        )
        return

    entries = "\n\n".join(
        f"{e('check') if selected and group.id == selected.id else e('family')} "
        f"<b>{safe(group.title)}</b>\n"
        f"{e('people')} {counts.get(group.id, 0)} nafar · "
        f"{e('alarm')} {group.reminder_time} · <code>{group.chat_id}</code>"
        for group in groups
    )

    unassigned = counts.get(None, 0)
    footer = ""

    if unassigned:
        footer = (
            f"{e('warning')} Guruhga biriktirilmagan insonlar: <b>{unassigned}</b>\n"
            + hint("Guruhni tanlab, /assign ID bilan biriktiring.")
        )

    current = (
        f"{e('target')} Tanlangan: <b>{safe(selected.title)}</b>"
        if selected
        else f"{e('target')} Guruh tanlanmagan — quyidan tanlang."
    )

    await message.answer(
        card(title("family", "Ulangan guruhlar"), entries, current, footer),
        reply_markup=_groups_keyboard(groups, selected.id if selected else None),
    )


@router.callback_query(F.data.startswith(GROUP_CALLBACK_PREFIX))
async def choose_group(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    if user_id not in settings.admin_ids or not await authorized(user_id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        group_id = int((callback.data or "").removeprefix(GROUP_CALLBACK_PREFIX))
    except ValueError:
        await callback.answer()
        return

    async with SessionLocal() as session:
        group = await session.get(GroupConfig, group_id)

        if group is None or not group.is_active:
            await callback.answer("Guruh topilmadi.", show_alert=True)
            return

        user = await _get_auth_user(session, user_id)

        if user is not None:
            user.selected_group_id = group.id
            await session.commit()

        group_title = group.title
        groups = await _active_groups(session)

    await callback.answer(f"Tanlandi: {group_title}"[:200])

    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=_groups_keyboard(groups, group_id)
            )
        except TelegramBadRequest:
            pass

        await callback.message.answer(
            f"{e('check')} Endi komandalar <b>{safe(group_title)}</b> "
            "guruhi jadvali bilan ishlaydi.\n"
            + hint("Jadval: /birthdays · Qo'shish: /add")
        )


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


async def _group_admin_check(message: Message) -> bool:
    if not message.from_user:
        return False

    if message.from_user.id not in settings.admin_ids:
        await message.answer(f"{e('cross')} Ushbu amal faqat administrator uchun.")
        return False

    if message.chat.type not in {"group", "supergroup"}:
        if await require_admin(message):
            await message.answer(
                card(
                    title("family", "Guruhni ulash"),
                    "1. Botni oilaviy guruhga qo'shing.\n"
                    "2. Botga xabar yuborish ruxsatini bering.\n"
                    "3. O'sha guruh ichida /setgroup yuboring.",
                )
            )
        return False

    if not await authorized(message.from_user.id):
        await message.answer(
            f"{e('lock')} Avval bot bilan shaxsiy chatda /start orqali "
            "avtorizatsiyadan o'ting."
        )
        return False

    return True


@router.message(Command("setgroup"))
async def set_group(message: Message) -> None:
    if not await _group_admin_check(message):
        return

    chat_id = message.chat.id
    chat_title = (message.chat.title or "Oila guruhi")[:255]

    async with SessionLocal() as session:
        cfg = await session.scalar(
            select(GroupConfig).where(GroupConfig.chat_id == chat_id)
        )
        is_new = cfg is None

        if cfg is None:
            cfg = GroupConfig(chat_id=chat_id)
            session.add(cfg)

        cfg.title = chat_title
        cfg.timezone = settings.timezone
        cfg.reminder_time = settings.birthday_reminder_time
        cfg.is_active = True
        await session.flush()

        # Shaxsiy chatdagi komandalar endi shu guruh bilan ishlaydi.
        user = await _get_auth_user(session, message.from_user.id)

        if user is not None:
            user.selected_group_id = cfg.id

        people_count = await session.scalar(
            select(func.count(Person.id)).where(
                Person.group_id == cfg.id,
                Person.is_active.is_(True),
            )
        )

        await session.commit()

    logger.info("Guruh ulandi: chat_id=%s, yangi=%s", chat_id, is_new)

    await message.answer(
        card(
            title("check", "Guruh ulandi" if is_new else "Guruh yangilandi"),
            row("family", "Guruh", f"<b>{safe(chat_title)}</b>")
            + "\n"
            + row("people", "Jadvalda", f"<b>{people_count or 0}</b> nafar")
            + "\n"
            + row("alarm", "Eslatma vaqti", f"<code>{settings.birthday_reminder_time}</code>")
            + "\n"
            + row("globe", "Vaqt zonasi", f"<code>{safe(settings.timezone)}</code>"),
            hint(
                "Bu guruh jadvaliga insonlarni bot bilan shaxsiy chatda "
                "/add orqali qo'shing — tabriklar faqat shu guruhga boradi."
            ),
        )
    )


@router.message(Command("removegroup"))
async def remove_group(message: Message) -> None:
    if not await _group_admin_check(message):
        return

    async with SessionLocal() as session:
        cfg = await session.scalar(
            select(GroupConfig).where(GroupConfig.chat_id == message.chat.id)
        )

        if cfg is None or not cfg.is_active:
            await message.answer(f"{e('bulb')} Bu guruh ulanmagan.")
            return

        # Yozuv o'chirilmaydi, faqat faolsizlantiriladi: jadval saqlanib
        # qoladi va /setgroup bilan qayta yoqish mumkin.
        cfg.is_active = False
        await session.commit()

    await message.answer(
        card(
            title("folder", "Guruh o'chirildi"),
            "Bu guruhga endi tabrik yuborilmaydi.\n"
            + hint("Jadval saqlanib qoldi. Qayta yoqish: /setgroup"),
        )
    )


@router.message(F.migrate_to_chat_id)
async def group_migrated(message: Message) -> None:
    """Oddiy guruh superguruhga aylanganda chat ID avtomatik yangilanadi."""

    await migrate_group_chat_id(message.chat.id, message.migrate_to_chat_id)


# ================================================================
# KO'RISH KOMANDALARI
# ================================================================

@router.message(Command("birthdays"))
async def birthdays_command(message: Message) -> None:
    group = await _view_group(message)

    if group is None:
        return

    async with SessionLocal() as session:
        people = await list_people(session, group.id)

    if not people:
        await message.answer(
            card(
                title("mailbox", "Jadval hozircha bo'sh"),
                _group_line(group),
                f"{e('plus')} Yangi inson qo'shish: /add",
            )
        )
        return

    await _send_long_text(
        message,
        birthday_table(people, local_today(), heading=f"{group.title} — tug'ilgan kunlar"),
    )


@router.message(Command("today"))
async def today_command(message: Message) -> None:
    group = await _view_group(message)

    if group is None:
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session, group.id)

    found = [
        person
        for person in people
        if birthday_date_for_year(person.birth_date, today.year) == today
    ]

    if not found:
        await message.answer(
            card(
                title("party", "Bugungi tug'ilgan kunlar"),
                _group_line(group)
                + f"\n{e('calendar')} {format_date_uz(today)}",
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
            _group_line(group) + f"\n{e('calendar')} {format_date_uz(today)}",
            entries,
        ),
    )


@router.message(Command("next"))
async def next_command(message: Message) -> None:
    group = await _view_group(message)

    if group is None:
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session, group.id)

    if not people:
        await message.answer(
            f"{e('mailbox')} <b>{safe(group.title)}</b> jadvali bo'sh. Qo'shish: /add"
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
            _group_line(group),
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
    group = await _view_group(message)

    if group is None:
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session, group.id)

    found = [
        person
        for person in people
        if days_until(person.birth_date, today) <= UPCOMING_DAYS
    ]

    if not found:
        await message.answer(
            card(
                title("bell", f"Keyingi {UPCOMING_DAYS} kun"),
                _group_line(group),
                "Ushbu davr ichida tug'ilgan kun yo'q.",
            )
        )
        return

    await _send_long_text(
        message,
        birthday_table(
            found,
            today,
            heading=f"{group.title} — keyingi {UPCOMING_DAYS} kun",
        ),
    )


# ================================================================
# QO'SHISH
# ================================================================

@router.message(Command("add"))
async def add_start(message: Message, state: FSMContext) -> None:
    group = await _admin_group(message)

    if group is None:
        return

    await state.clear()
    await state.update_data(group_id=group.id, group_title=group.title)
    await state.set_state(AddStates.name)

    await message.answer(
        card(
            title("plus", "Yangi inson qo'shish"),
            _group_line(group),
            f"{e('pencil')} <b>1/2</b> · To'liq ismni kiriting.\n"
            f"{hint('Masalan: Ali Valiyev')}",
            hint("Boshqa guruhga qo'shish uchun: /groups") + "\n" + CANCEL_HINT,
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
    group_id = data.get("group_id")

    if not full_name or not group_id:
        await state.clear()
        await message.answer(
            f"{e('warning')} Jarayon holati yo'qolgan. Qayta /add yuboring."
        )
        return

    async with SessionLocal() as session:
        group = await session.get(GroupConfig, int(group_id))

        if group is None or not group.is_active:
            await state.clear()
            await message.answer(
                f"{e('warning')} Guruh topilmadi yoki o'chirilgan. /groups"
            )
            return

        person = Person(full_name=full_name, birth_date=birth_date, group_id=group.id)
        session.add(person)
        await session.commit()
        await session.refresh(person)
        person_id = person.id
        group_title = group.title

    await state.clear()

    await message.answer(
        card(
            title("check", "Inson muvaffaqiyatli qo'shildi"),
            row("person", "Ism", f"<b>{safe(full_name)}</b>")
            + "\n"
            + row("calendar", "Tug'ilgan sana", format_date_uz(birth_date))
            + "\n"
            + row("family", "Guruh", f"<b>{safe(group_title)}</b>")
            + "\n"
            + row("key", "ID", f"<code>{person_id}</code>"),
            f"{e('picture')} Surat: <code>/setphoto {person_id}</code>\n"
            f"{e('music')} Musiqa: <code>/setmusic {person_id}</code>\n"
            f"{e('pencil')} Tahrirlash: <code>/edit {person_id}</code>",
        )
    )


# ================================================================
# TAHRIRLASH, ARXIVLASH, KO'CHIRISH
# ================================================================

@router.message(Command("edit"))
async def edit_start(message: Message, state: FSMContext) -> None:
    group = await _admin_group(message)

    if group is None:
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("pencil", "/edit ID", "/edit 5"))
        return

    async with SessionLocal() as session:
        person = await _get_person(session, person_id, group.id)

        if person is None:
            await message.answer(_not_found_text(group))
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
        person = await _get_person(session, int(person_id or 0), None)

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
    group = await _admin_group(message)

    if group is None:
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("folder", "/delete ID", "/delete 5"))
        return

    async with SessionLocal() as session:
        person = await _get_person(session, person_id, group.id)

        if person is None:
            await message.answer(_not_found_text(group))
            return

        person.is_active = False
        await session.commit()
        name = person.full_name

    await message.answer(
        card(
            title("folder", "Inson arxivlandi"),
            row("person", "Ism", f"<b>{safe(name)}</b>") + "\n" + _group_line(group),
            hint("U jadval va kelgusi eslatmalarda qatnashmaydi."),
        )
    )


@router.message(Command("assign"))
async def assign_person(message: Message) -> None:
    group = await _admin_group(message)

    if group is None:
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("family", "/assign ID", "/assign 5"))
        return

    async with SessionLocal() as session:
        person = await _get_person(session, person_id, None)

        if person is None:
            await message.answer(_not_found_text())
            return

        person.group_id = group.id
        await session.commit()
        name = person.full_name

    await message.answer(
        card(
            title("check", "Inson guruhga biriktirildi"),
            row("person", "Ism", f"<b>{safe(name)}</b>") + "\n" + _group_line(group),
            hint("Tabriklar endi faqat shu guruhga yuboriladi."),
        )
    )


# ================================================================
# MEDIA
# ================================================================

async def _start_media(
    message: Message,
    state: FSMContext,
    target_state: State,
    emoji_key: str,
    command: str,
    prompt: str,
) -> None:
    group = await _admin_group(message)

    if group is None:
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage(emoji_key, f"/{command} ID", f"/{command} 5"))
        return

    async with SessionLocal() as session:
        person = await _get_person(session, person_id, group.id)

        if person is None:
            await message.answer(_not_found_text(group))
            return

        name = person.full_name

    await state.clear()
    await state.update_data(media_person_id=person_id)
    await state.set_state(target_state)

    await message.answer(
        f"{e(emoji_key)} <b>{safe(name)}</b> uchun {prompt}\n\n{CANCEL_HINT}"
    )


async def _save_media(
    message: Message,
    state: FSMContext,
    field_name: str,
    file_id: str,
    saved_text: str,
) -> None:
    data = await state.get_data()
    person_id = data.get("media_person_id")

    if not person_id:
        await state.clear()
        await message.answer(
            f"{e('warning')} Yuklash sessiyasi topilmadi. Qayta urinib ko'ring."
        )
        return

    async with SessionLocal() as session:
        person = await _get_person(session, int(person_id), None)

        if person is None:
            await state.clear()
            await message.answer(_not_found_text())
            return

        setattr(person, field_name, file_id)
        await session.commit()
        name = person.full_name

    await state.clear()

    await message.answer(
        f"{e('check')} <b>{saved_text}</b>\n"
        f"{e('person')} Inson: <b>{safe(name)}</b>"
    )


@router.message(Command("setphoto"))
async def set_photo_start(message: Message, state: FSMContext) -> None:
    await _start_media(
        message,
        state,
        MediaStates.waiting_photo,
        "picture",
        "setphoto",
        "surat yuboring (oddiy rasm sifatida).",
    )


@router.message(MediaStates.waiting_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return

    await _save_media(
        message, state, "photo_file_id", message.photo[-1].file_id, "Surat saqlandi."
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
    await _start_media(
        message,
        state,
        MediaStates.waiting_audio,
        "music",
        "setmusic",
        "audio yuboring.\n"
        + hint("Audio yoki audio formatdagi hujjat (20 MB gacha)."),
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

    await _save_media(message, state, "music_file_id", file_id, "Musiqa saqlandi.")


@router.message(MediaStates.waiting_audio)
async def invalid_audio_input(message: Message) -> None:
    if not await require_admin(message):
        return

    await message.answer(
        f"{e('warning')} Iltimos, audio yoki audio formatdagi hujjat yuboring.\n"
        f"{CANCEL_HINT}"
    )


# ================================================================
# TEST VA HOLAT
# ================================================================

@router.message(Command("testbirthday"))
async def test_birthday(message: Message, bot: Bot) -> None:
    group = await _admin_group(message)

    if group is None:
        return

    person_id = _parse_person_id(message)

    if person_id is None:
        await message.answer(_usage("party", "/testbirthday ID", "/testbirthday 5"))
        return

    async with SessionLocal() as session:
        person = await _get_person(session, person_id, group.id)

        if person is None:
            await message.answer(_not_found_text(group))
            return

        person_data = PersonData.from_person(person)

    await message.answer(
        f"{e('rocket')} <b>Test tabrigi yuborilmoqda...</b>\n"
        f"{e('person')} {safe(person_data.full_name)} → "
        f"{e('family')} {safe(group.title)}"
    )

    result = await send_birthday_greeting(bot, group.chat_id, person_data, local_today())

    lines = [
        f"{e('check')} Tabrik yuborildi"
        if result.greeting_sent
        else f"{e('cross')} Tabrik yuborilmadi"
    ]

    if result.music_sent:
        lines.append(f"{e('music')} Musiqa yuborildi")
    elif person_data.music_file_id and result.greeting_sent:
        lines.append(f"{e('warning')} Musiqa yuborilmadi")

    if result.error:
        lines.append(f"{e('warning')} <code>{safe(result.error[:300])}</code>")

    if result.music_error:
        lines.append(f"{e('music')} <code>{safe(result.music_error[:300])}</code>")

    await message.answer(
        card(
            title("sparkles", "Test natijasi"),
            row("person", "Inson", f"<b>{safe(person_data.full_name)}</b>")
            + "\n"
            + _group_line(group),
            DIVIDER,
            "\n".join(lines),
        )
    )


@router.message(Command("status"))
async def status_command(message: Message) -> None:
    if not await require_admin(message):
        return

    try:
        async with SessionLocal() as session:
            groups = await _active_groups(session)
            selected = await _selected_group(session, message.from_user.id)
            active_count = await session.scalar(
                select(func.count(Person.id)).where(Person.is_active.is_(True))
            )

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
            row("family", "Faol guruhlar", f"<b>{len(groups)}</b>")
            + "\n"
            + row("people", "Jami insonlar", f"<b>{active_count or 0}</b>")
            + "\n"
            + row(
                "target",
                "Tanlangan guruh",
                f"<b>{safe(selected.title)}</b>" if selected else "tanlanmagan",
            )
            + "\n"
            + row("alarm", "Eslatma vaqti", f"<code>{settings.birthday_reminder_time}</code>")
            + "\n"
            + row("globe", "Vaqt zonasi", f"<code>{safe(settings.timezone)}</code>"),
        )
    )
