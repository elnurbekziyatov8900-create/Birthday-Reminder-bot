from datetime import datetime
from html import escape

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AuthUser, Person, GroupConfig
from app.services import (
    age_on,
    birthday_table,
    list_people,
    local_today,
    days_until,
)

router = Router()
settings = get_settings()


# ============================================================
# FSM STATES
# ============================================================

class AuthStates(StatesGroup):
    waiting_password = State()


class AddStates(StatesGroup):
    name = State()
    birth_date = State()


# ============================================================
# TEXTS
# ============================================================

WELCOME_TEXT = (
    "🎂 <b>Family Birthday Assistant</b>\n\n"
    "Assalomu alaykum! 👋\n\n"
    "Oilangiz uchun muhim sanalarni eslab qolish endi oson!\n\n"
    "🔐 Botdan foydalanish uchun oilaviy kirish parolini yuboring."
)

AUTH_SUCCESS_TEXT = (
    "✅ <b>Muvaffaqiyatli kirdingiz!</b>\n\n"
    "🎉 Family Birthday Assistant xizmatiga xush kelibsiz!\n\n"
    "Quyidagi komandalar orqali botni boshqarishingiz mumkin:\n\n"
    "📋 /help — yordam va komandalar\n"
    "🎂 /birthdays — barcha tug‘ilgan kunlar\n"
    "🎉 /today — bugungi tug‘ilgan kunlar\n"
    "⏳ /next — eng yaqin tug‘ilgan kun\n"
    "📅 /upcoming — keyingi 30 kun\n"
    "➕ /add — yangi inson qo‘shish\n"
    "📊 /status — bot holati"
)

HELP_TEXT = (
    "🎂 <b>Family Birthday Assistant</b>\n"
    "<i>Komandalar qo‘llanmasi</i>\n\n"
    "📅 <b>TUG‘ILGAN KUNLAR</b>\n"
    "/birthdays — barcha tug‘ilgan kunlar\n"
    "/today — bugungi tug‘ilgan kunlar\n"
    "/next — eng yaqin tug‘ilgan kun\n"
    "/upcoming — keyingi 30 kun ichidagi sanalar\n\n"
    "👤 <b>MA’LUMOTLARNI BOSHQARISH</b>\n"
    "/add — yangi inson qo‘shish\n"
    "/edit ID — tahrirlash bo‘yicha yo‘riqnoma\n"
    "/delete ID — insonni arxivlash\n"
    "/setphoto ID — surat biriktirish\n"
    "/setmusic ID — musiqa biriktirish\n\n"
    "👨‍👩‍👧‍👦 <b>GURUH VA TABRIKLAR</b>\n"
    "/setgroup — joriy guruhni eslatma guruhi qilish\n"
    "/testbirthday ID — test tabrigini yuborish\n\n"
    "⚙️ <b>TIZIM</b>\n"
    "/status — bot holati\n"
    "/cancel — joriy amalni bekor qilish\n"
    "/help — ushbu qo‘llanma"
)


# ============================================================
# AUTHORIZATION
# ============================================================

def is_admin_id(user_id: int) -> bool:
    """Foydalanuvchi ruxsat berilgan administrator ekanini tekshiradi."""
    return user_id in settings.admin_ids


async def authorized(user_id: int) -> bool:
    """Administrator autentifikatsiyadan o‘tganini tekshiradi."""
    if not is_admin_id(user_id):
        return False

    async with SessionLocal() as session:
        user = await session.scalar(
            select(AuthUser).where(
                AuthUser.telegram_user_id == user_id
            )
        )

        return bool(user and user.is_authenticated)


async def require_admin(message: Message) -> bool:
    """Komandani bajarishdan oldin administrator huquqini tekshiradi."""
    if message.chat.type != "private":
        if not message.from_user or not await authorized(
            message.from_user.id
        ):
            await message.answer(
                "🔒 <b>Kirish cheklangan</b>\n\n"
                "Iltimos, botni shaxsiy chatda ochib, "
                "/start orqali tizimga kiring.",
                parse_mode="HTML",
            )
            return False

        return True

    if not message.from_user:
        await message.answer("❌ Foydalanuvchi aniqlanmadi.")
        return False

    if not is_admin_id(message.from_user.id):
        await message.answer(
            "⛔ <b>Kirishga ruxsat yo‘q</b>\n\n"
            "Ushbu bot faqat ruxsat berilgan "
            "administratorlar uchun mo‘ljallangan.",
            parse_mode="HTML",
        )
        return False

    if not await authorized(message.from_user.id):
        await message.answer(
            "🔐 <b>Avtorizatsiya talab qilinadi</b>\n\n"
            "Botdan foydalanish uchun shaxsiy chatda "
            "/start yuboring.",
            parse_mode="HTML",
        )
        return False

    return True


# ============================================================
# START
# ============================================================

@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer(
            "🔐 <b>Xavfsizlik xabari</b>\n\n"
            "Iltimos, botni shaxsiy chatda ochib, "
            "/start komandasini yuboring.",
            parse_mode="HTML",
        )
        return

    if not message.from_user:
        return

    if not is_admin_id(message.from_user.id):
        await message.answer(
            "⛔ <b>Kirishga ruxsat yo‘q</b>\n\n"
            "Kechirasiz, siz ushbu botdan foydalanish "
            "uchun ruxsat olmagansiz.",
            parse_mode="HTML",
        )
        return

    if await authorized(message.from_user.id):
        await state.clear()

        await message.answer(
            "🎂 <b>Family Birthday Assistant</b>\n\n"
            "Qayta xush kelibsiz! 👋\n\n"
            "Bot ishlashga tayyor.\n"
            "📋 Komandalar ro‘yxati: /help\n\n"
            "🎉 Yaqin tug‘ilgan kunlarni tekshirish: /upcoming",
            parse_mode="HTML",
        )
        return

    await state.set_state(AuthStates.waiting_password)

    await message.answer(
        WELCOME_TEXT,
        parse_mode="HTML",
    )


# ============================================================
# PASSWORD INPUT
# ============================================================

@router.message(AuthStates.waiting_password, F.text)
async def password_input(message: Message, state: FSMContext):
    if not message.from_user:
        return

    if not is_admin_id(message.from_user.id):
        await state.clear()
        return

    password = (message.text or "").strip()

    # Parol Telegram chatida saqlanib qolmasligi uchun
    # foydalanuvchi yuborgan xabarni o‘chirishga harakat qilamiz.
    try:
        await message.delete()
    except Exception:
        pass

    # Kutish holatida komandalar parol sifatida qabul qilinmasin.
    if password.startswith("/"):
        if password.split()[0].split("@")[0] == "/cancel":
            await state.clear()
            await message.answer(
                "↩️ Kirish jarayoni bekor qilindi.\n\n"
                "Qayta boshlash uchun /start yuboring."
            )
            return

        await message.answer(
            "🔐 <b>Parol kutilmoqda</b>\n\n"
            "Iltimos, kirish parolini yuboring.\n"
            "Bekor qilish uchun /cancel yuboring.",
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
            )
            session.add(user)
            await session.flush()

        if password == settings.bot_access_password:
            user.is_authenticated = True
            user.failed_attempts = 0
            user.last_authenticated_at = datetime.utcnow()

            await session.commit()
            await state.clear()

            await message.answer(
                AUTH_SUCCESS_TEXT,
                parse_mode="HTML",
            )

        else:
            user.failed_attempts += 1
            attempts = user.failed_attempts

            await session.commit()

            await message.answer(
                "❌ <b>Parol noto‘g‘ri</b>\n\n"
                "Iltimos, parolni tekshirib, qayta urinib ko‘ring.\n\n"
                f"🔢 Noto‘g‘ri urinishlar: <b>{attempts}</b>\n\n"
                "↩️ Bekor qilish: /cancel",
                parse_mode="HTML",
            )


# ============================================================
# HELP
# ============================================================

@router.message(Command("help"))
async def help_command(message: Message):
    if not await require_admin(message):
        return

    await message.answer(
        HELP_TEXT,
        parse_mode="HTML",
    )


# ============================================================
# ALL BIRTHDAYS
# ============================================================

@router.message(Command("birthdays"))
async def birthdays(message: Message):
    if not await require_admin(message):
        return

    async with SessionLocal() as session:
        people = await list_people(session)

    if not people:
        await message.answer(
            "📭 <b>Hozircha tug‘ilgan kunlar yo‘q</b>\n\n"
            "Yangi inson qo‘shish uchun /add komandasidan foydalaning.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        birthday_table(people, local_today()),
        parse_mode="HTML",
    )


# ============================================================
# TODAY'S BIRTHDAYS
# ============================================================

@router.message(Command("today"))
async def today_command(message: Message):
    if not await require_admin(message):
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session)

    found = [
        person
        for person in people
        if (
            person.birth_date.month,
            person.birth_date.day,
        ) == (
            today.month,
            today.day,
        )
    ]

    if not found:
        await message.answer(
            "🎉 <b>Bugungi tug‘ilgan kunlar</b>\n\n"
            "Bugun bazada tug‘ilgan kuni bo‘lgan "
            "inson topilmadi.\n\n"
            "Yangi kun — yangi quvonch! 💛",
            parse_mode="HTML",
        )
        return

    lines = [
        "🎉 <b>Bugungi tug‘ilgan kunlar</b>\n"
    ]

    for person in found:
        name = escape(person.full_name)
        age = age_on(person.birth_date, today)

        lines.append(
            f"🎂 <b>{name}</b> — {age} yosh"
        )

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
    )


# ============================================================
# NEXT BIRTHDAY
# ============================================================

@router.message(Command("next"))
async def next_command(message: Message):
    if not await require_admin(message):
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session)

    if not people:
        await message.answer(
            "📭 <b>Bazada ma’lumot yo‘q</b>\n\n"
            "Yangi inson qo‘shish uchun /add yuboring.",
            parse_mode="HTML",
        )
        return

    person = min(
        people,
        key=lambda item: (
            days_until(item.birth_date, today),
            item.full_name.casefold(),
        ),
    )

    name = escape(person.full_name)
    remaining = days_until(person.birth_date, today)

    if remaining == 0:
        countdown = "🎉 Bugun tug‘ilgan kuni!"
    elif remaining == 1:
        countdown = "⏳ Ertaga!"
    else:
        countdown = f"⏳ {remaining} kun qoldi"

    await message.answer(
        "🎂 <b>Eng yaqin tug‘ilgan kun</b>\n\n"
        f"👤 Ism: <b>{name}</b>\n"
        f"📅 Tug‘ilgan sana: {person.birth_date:%d.%m.%Y}\n"
        f"{countdown}",
        parse_mode="HTML",
    )


# ============================================================
# UPCOMING BIRTHDAYS
# ============================================================

@router.message(Command("upcoming"))
async def upcoming(message: Message):
    if not await require_admin(message):
        return

    today = local_today()

    async with SessionLocal() as session:
        people = await list_people(session)

    found = sorted(
        [
            person
            for person in people
            if days_until(person.birth_date, today) <= 30
        ],
        key=lambda person: (
            days_until(person.birth_date, today),
            person.full_name.casefold(),
        ),
    )

    if not found:
        await message.answer(
            "📅 <b>Yaqinlashayotgan tug‘ilgan kunlar</b>\n\n"
            "Keyingi 30 kun ichida tug‘ilgan kuni "
            "bo‘lgan inson topilmadi.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "📅 <b>Keyingi 30 kun ichidagi tug‘ilgan kunlar</b>\n\n"
        + birthday_table(found, today),
        parse_mode="HTML",
    )


# ============================================================
# ADD PERSON — START
# ============================================================

@router.message(Command("add"))
async def add_start(message: Message, state: FSMContext):
    if not await require_admin(message):
        return

    await state.set_state(AddStates.name)

    await message.answer(
        "➕ <b>Yangi inson qo‘shish</b>\n\n"
        "1️⃣ Insonning to‘liq ismini kiriting.\n\n"
        "Masalan: <i>Ali Valiyev</i>\n\n"
        "Bekor qilish uchun /cancel yuboring.",
        parse_mode="HTML",
    )


# ============================================================
# ADD PERSON — NAME
# ============================================================

@router.message(AddStates.name, F.text)
async def add_name(message: Message, state: FSMContext):
    if not await require_admin(message):
        return

    name = (message.text or "").strip()

    if name.startswith("/"):
        await message.answer(
            "✏️ Iltimos, insonning to‘liq ismini kiriting.\n"
            "Bekor qilish uchun /cancel yuboring."
        )
        return

    if len(name) < 2 or len(name) > 200:
        await message.answer(
            "⚠️ Ism 2–200 belgi oralig‘ida bo‘lishi kerak.\n\n"
            "Iltimos, qayta kiriting."
        )
        return

    await state.update_data(full_name=name)
    await state.set_state(AddStates.birth_date)

    await message.answer(
        "📅 <b>Tug‘ilgan sanani kiriting</b>\n\n"
        "Sanani <code>DD.MM.YYYY</code> formatida yuboring.\n\n"
        "Masalan: <code>25.10.2005</code>",
        parse_mode="HTML",
    )


# ============================================================
# ADD PERSON — BIRTH DATE
# ============================================================

@router.message(AddStates.birth_date, F.text)
async def add_date(message: Message, state: FSMContext):
    if not await require_admin(message):
        return

    raw_date = (message.text or "").strip()

    if raw_date.startswith("/"):
        await message.answer(
            "📅 Tug‘ilgan sanani <code>DD.MM.YYYY</code> "
            "formatida yuboring.\n"
            "Bekor qilish uchun /cancel yuboring.",
            parse_mode="HTML",
        )
        return

    try:
        birth_date = datetime.strptime(
            raw_date,
            "%d.%m.%Y",
        ).date()

        if birth_date > local_today() or birth_date.year < 1900:
            raise ValueError

    except ValueError:
        await message.answer(
            "❌ <b>Sana noto‘g‘ri kiritildi</b>\n\n"
            "Quyidagi formatdan foydalaning:\n"
            "<code>DD.MM.YYYY</code>\n\n"
            "Masalan: <code>25.10.2005</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    full_name = data["full_name"]

    async with SessionLocal() as session:
        person = Person(
            full_name=full_name,
            birth_date=birth_date,
        )

        session.add(person)
        await session.commit()
        await session.refresh(person)

        person_id = person.id

    await state.clear()

    safe_name = escape(full_name)

    await message.answer(
        "✅ <b>Yangi inson muvaffaqiyatli qo‘shildi!</b>\n\n"
        f"👤 Ism: <b>{safe_name}</b>\n"
        f"📅 Tug‘ilgan sana: <code>{birth_date:%d.%m.%Y}</code>\n"
        f"🆔 ID: <code>{person_id}</code>\n\n"
        "🖼 Surat biriktirish:\n"
        f"<code>/setphoto {person_id}</code>\n\n"
        "🎵 Musiqa biriktirish:\n"
        f"<code>/setmusic {person_id}</code>",
        parse_mode="HTML",
    )


# ============================================================
# DELETE PERSON
# ============================================================

@router.message(Command("delete"))
async def delete_person(message: Message):
    if not await require_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "🗑 <b>Insonni arxivlash</b>\n\n"
            "Foydalanish:\n"
            "<code>/delete ID</code>\n\n"
            "Masalan: <code>/delete 5</code>",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        person = await session.get(Person, int(parts[1]))

        if not person or not person.is_active:
            await message.answer(
                "❌ Bunday faol ID topilmadi.",
            )
            return

        person.is_active = False
        await session.commit()

        name = escape(person.full_name)

    await message.answer(
        "✅ <b>Inson arxivlandi</b>\n\n"
        f"👤 {name}\n\n"
        "U faol tug‘ilgan kunlar ro‘yxatida "
        "ko‘rinmasligi kerak.",
        parse_mode="HTML",
    )


# ============================================================
# EDIT PERSON
# ============================================================

@router.message(Command("edit"))
async def edit_person(message: Message):
    if not await require_admin(message):
        return

    await message.answer(
        "✏️ <b>Ma’lumotlarni tahrirlash</b>\n\n"
        "Ushbu versiyada tahrirlash dialogi "
        "hali amalga oshirilmagan.\n\n"
        "⚠️ Ma’lumotni o‘zgartirish uchun hozircha "
        "o‘chirish yoki qayta qo‘shishdan oldin "
        "ma’lumotlar bazasining zaxira nusxasini oling.",
        parse_mode="HTML",
    )


# ============================================================
# SET PHOTO
# ============================================================

@router.message(Command("setphoto"))
async def setphoto(message: Message, state: FSMContext):
    if not await require_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "🖼 <b>Surat biriktirish</b>\n\n"
            "Foydalanish:\n"
            "<code>/setphoto ID</code>\n\n"
            "Masalan: <code>/setphoto 5</code>",
            parse_mode="HTML",
        )
        return

    person_id = int(parts[1])

    async with SessionLocal() as session:
        person = await session.get(Person, person_id)

        if not person or not person.is_active:
            await message.answer(
                "❌ Faol inson topilmadi.",
            )
            return

    await state.update_data(
        media_person_id=person_id,
        media_type="photo",
    )

    await message.answer(
        "🖼 <b>Surat yuborish</b>\n\n"
        "Endi shu chatga kerakli insonning suratini yuboring.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


# ============================================================
# SET MUSIC
# ============================================================

@router.message(Command("setmusic"))
async def setmusic(message: Message, state: FSMContext):
    if not await require_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "🎵 <b>Musiqa biriktirish</b>\n\n"
            "Foydalanish:\n"
            "<code>/setmusic ID</code>\n\n"
            "Masalan: <code>/setmusic 5</code>",
            parse_mode="HTML",
        )
        return

    person_id = int(parts[1])

    async with SessionLocal() as session:
        person = await session.get(Person, person_id)

        if not person or not person.is_active:
            await message.answer(
                "❌ Faol inson topilmadi.",
            )
            return

    await state.update_data(
        media_person_id=person_id,
        media_type="audio",
    )

    await message.answer(
        "🎵 <b>Musiqa yuborish</b>\n\n"
        "Endi shu chatga audio yoki musiqa faylini yuboring.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


# ============================================================
# PHOTO UPLOAD
# ============================================================

@router.message(F.photo)
async def photo_upload(message: Message, state: FSMContext):
    if not message.from_user:
        return

    if not await authorized(message.from_user.id):
        return

    data = await state.get_data()

    if data.get("media_type") != "photo":
        return

    person_id = data.get("media_person_id")

    async with SessionLocal() as session:
        person = await session.get(Person, person_id)

        if not person or not person.is_active:
            await state.clear()
            await message.answer(
                "❌ Inson topilmadi yoki arxivlangan.",
            )
            return

        person.photo_file_id = message.photo[-1].file_id
        await session.commit()

        name = escape(person.full_name)

    await state.clear()

    await message.answer(
        "✅ <b>Surat saqlandi!</b>\n\n"
        f"👤 Inson: {name}\n"
        "🖼 Surat tug‘ilgan kun tabrigida "
        "ishlatilishi mumkin.",
        parse_mode="HTML",
    )


# ============================================================
# AUDIO UPLOAD
# ============================================================

@router.message(F.audio | F.document)
async def audio_upload(message: Message, state: FSMContext):
    if not message.from_user:
        return

    if not await authorized(message.from_user.id):
        return

    data = await state.get_data()

    if data.get("media_type") != "audio":
        return

    if message.audio:
        file_id = message.audio.file_id
    elif message.document:
        file_id = message.document.file_id
    else:
        return

    person_id = data.get("media_person_id")

    async with SessionLocal() as session:
        person = await session.get(Person, person_id)

        if not person or not person.is_active:
            await state.clear()
            await message.answer(
                "❌ Inson topilmadi yoki arxivlangan.",
            )
            return

        person.music_file_id = file_id
        await session.commit()

        name = escape(person.full_name)

    await state.clear()

    await message.answer(
        "✅ <b>Audio saqlandi!</b>\n\n"
        f"👤 Inson: {name}\n"
        "🎵 Audio tug‘ilgan kun tabrigida "
        "ishlatilishi mumkin.",
        parse_mode="HTML",
    )


# ============================================================
# SET REMINDER GROUP
# ============================================================

@router.message(Command("setgroup"))
async def setgroup(message: Message):
    if not await require_admin(message):
        return

    if message.chat.type == "private":
        await message.answer(
            "👨‍👩‍👧‍👦 <b>Guruhni sozlash</b>\n\n"
            "Avval botni oilaviy guruhga qo‘shing.\n"
            "Keyin guruh ichida /setgroup komandasini yuboring.",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        cfg = await session.scalar(
            select(GroupConfig).where(
                GroupConfig.chat_id == message.chat.id
            )
        )

        if cfg is None:
            cfg = GroupConfig(
                chat_id=message.chat.id,
                title=message.chat.title or "Family group",
                timezone=settings.timezone,
                reminder_time=settings.birthday_reminder_time,
            )
            session.add(cfg)
        else:
            cfg.is_active = True

        await session.commit()

    await message.answer(
        "✅ <b>Guruh muvaffaqiyatli sozlandi!</b>\n\n"
        f"👨‍👩‍👧‍👦 Guruh: {escape(message.chat.title or 'Family group')}\n"
        f"🕘 Eslatma vaqti: {settings.birthday_reminder_time}\n"
        f"🌍 Vaqt zonasi: {settings.timezone}",
        parse_mode="HTML",
    )


# ============================================================
# TEST BIRTHDAY
# ============================================================

@router.message(Command("testbirthday"))
async def test_birthday(message: Message, bot: Bot):
    if not await require_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "🎉 <b>Test tabrigi</b>\n\n"
            "Foydalanish:\n"
            "<code>/testbirthday ID</code>\n\n"
            "Masalan: <code>/testbirthday 5</code>",
            parse_mode="HTML",
        )
        return

    async with SessionLocal() as session:
        person = await session.get(Person, int(parts[1]))

        if not person or not person.is_active:
            await message.answer(
                "❌ Faol inson topilmadi.",
            )
            return

        from app.services import make_greeting

        greeting = make_greeting(person, local_today())

        group_id = settings.target_group_id

        if not group_id:
            cfg = await session.scalar(
                select(GroupConfig).where(
                    GroupConfig.is_active.is_(True)
                )
            )

            if cfg:
                group_id = cfg.chat_id

        if not group_id:
            await message.answer(
                "⚠️ <b>Guruh sozlanmagan</b>\n\n"
                "Oilaviy guruhda /setgroup komandasini yuboring "
                "yoki TARGET_GROUP_ID sozlamasini tekshiring.",
                parse_mode="HTML",
            )
            return

        photo_file_id = person.photo_file_id
        music_file_id = person.music_file_id
        full_name = escape(person.full_name)

    if photo_file_id:
        sent = await bot.send_photo(
            chat_id=group_id,
            photo=photo_file_id,
            caption=greeting,
            parse_mode="HTML",
        )
    else:
        sent = await bot.send_message(
            chat_id=group_id,
            text=greeting,
            parse_mode="HTML",
        )

    if music_file_id:
        await bot.send_audio(
            chat_id=group_id,
            audio=music_file_id,
            caption=f"🎵 {full_name} uchun tabrik musiqasi",
            parse_mode="HTML",
        )

    await message.answer(
        "✅ <b>Test tabrigi yuborildi!</b>\n\n"
        f"👤 Inson: {full_name}\n"
        f"🆔 Xabar ID: <code>{sent.message_id}</code>",
        parse_mode="HTML",
    )


# ============================================================
# BOT STATUS
# ============================================================

@router.message(Command("status"))
async def status(message: Message):
    if not await require_admin(message):
        return

    async with SessionLocal() as session:
        people = await list_people(session)

    await message.answer(
        "📊 <b>Bot holati</b>\n\n"
        "🟢 Bot: ishlayapti\n"
        "🗄 Ma’lumotlar bazasi: ulandi\n"
        f"👥 Faol insonlar: {len(people)}\n"
        f"🕘 Eslatma vaqti: {settings.birthday_reminder_time}\n"
        f"🌍 Vaqt zonasi: {settings.timezone}",
        parse_mode="HTML",
    )


# ============================================================
# CANCEL
# ============================================================

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "↩️ <b>Joriy amal bekor qilindi.</b>\n\n"
        "Davom etish uchun kerakli komandani tanlang:\n"
        "📋 /help — komandalar ro‘yxati\n"
        "🎂 /birthdays — tug‘ilgan kunlar",
        parse_mode="HTML",
    )