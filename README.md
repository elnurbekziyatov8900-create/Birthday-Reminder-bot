# Family Birthday Assistant

Telegram oilaviy tug‘ilgan kun boti. Python 3.11, aiogram 3, PostgreSQL, SQLAlchemy va APScheduler.

## 1. Talablar
- Python 3.11
- Docker Desktop
- Telegram bot tokeni (BotFather)
- Telegram user ID (administrator)
- Telegram guruhida botga xabar yuborish huquqi

## 2. PowerShell orqali sozlash

```powershell
cd C:\Users\$env:USERNAME
mkdir family_birthday_bot
cd family_birthday_bot
```

ZIP ichidagi fayllarni shu papkaga chiqaring. Keyin:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` faylini VS Code'da ochib `BOT_TOKEN`, `ADMIN_USER_IDS` va database parolini sozlang.

## 3. PostgreSQL

Docker Desktop ishga tushgan bo‘lsin:

```powershell
docker compose up -d db
docker compose ps
```

`.env` ichidagi `DATABASE_URL` quyidagi shaklda bo‘lsin; parol `.env` dagi `POSTGRES_PASSWORD` bilan mos bo‘lishi kerak (compose uni `.env` dan oladi):

`postgresql+asyncpg://birthday_user:change_this_password@localhost:5437/birthday_db`

Production uchun `change_this_password` o‘rniga kuchli parol qo‘ying.

## 4. Botni ishga tushirish

```powershell
python -m app.main
```

Bot bilan shaxsiy chatni oching, `/start` yuboring va `.env` dagi `BOT_ACCESS_PASSWORD` parolini kiriting. `ADMIN_USER_IDS` ichida aynan sizning Telegram user ID raqamingiz bo‘lishi shart.

## 5. Guruhni ulash
1. Botni oilaviy guruhga qo‘shing.
2. Botga xabar yuborish ruxsatini bering.
3. Guruh ichida `/setgroup` yuboring — bu guruh **asosiy guruh** bo‘ladi, eski guruhlar bazadan o‘chiriladi.
4. `.env` dagi `TARGET_GROUP_ID` faqat bazada birorta ham guruh bo‘lmaganda zaxira sifatida ishlatiladi.
5. Superguruh ID si doim `-100` bilan boshlanadi (masalan `-1001234567890`). To‘g‘ri ID ni guruh ichida `/chatid` orqali bilib oling.
6. Oddiy guruh superguruhga aylansa, bot yangi ID ni avtomatik saqlaydi.

## 6. Asosiy komandalar
- `/start` — autentifikatsiya
- `/help` — komandalar
- `/add` — inson qo‘shish
- `/birthdays` — kalendar ro‘yxati
- `/today` — bugungi tug‘ilgan kunlar
- `/next` — eng yaqin tug‘ilgan kun
- `/upcoming` — keyingi 30 kun
- `/setphoto ID` — surat biriktirish
- `/setmusic ID` — audio biriktirish
- `/testbirthday ID` — test tabrigi
- `/groups` — ulangan guruhlar
- `/setgroup` — joriy guruhni asosiy guruh qilish
- `/chatid` — chat ID
- `/delete ID` — insonni arxivlash
- `/status` — holat
- `/cancel` — dialogni bekor qilish

## 7. Animatsiyali emojilar
Xabarlarda Telegramning rasmiy **Animated Emoji** to‘plamidagi (`RestrictedEmoji`) custom emojilar ishlatiladi. Barcha ID lar `app/ui.py` da.

- Bot animatsiyali emoji yubora olishi uchun **bot egasida (BotFather akkaunti) Telegram Premium** bo‘lishi kerak (Bot API 9.4). Premium bo‘lmasa, xabar baribir yetib boradi, faqat oddiy emoji ko‘rinadi.
- ID larni tekshirish: `python -m app.check_emoji`
- Dizaynni o‘zingizga yuborib ko‘rish: `python -m app.test_emoji_send`
- Guruhlarni tekshirish: `python -m app.check_groups`

## Muhim
- Baza sxemasi ishga tushganda avtomatik yangilanadi (`init_db`), Docker'da esa avval `alembic upgrade head` bajariladi.
- Scheduler faqat bot ishlayotgan vaqtda ishlaydi.
- Administrator autentifikatsiyasi `ADMIN_USER_IDS` bilan cheklangan; bu qiymatni taxmin qilmang, o‘zingizning Telegram ID raqamingizni qo‘ying.
- Parol shaxsiy chatda kiritiladi. Telegram xabarini o‘chirishga ruxsat bermasa, bot o‘chirishni kafolatlay olmaydi.
- Tabrik va she’rlar hozircha lokal shablonlardan yaratiladi.
