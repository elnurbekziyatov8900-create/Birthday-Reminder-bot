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

## 5. Guruhlar va oila jadvallari
Bot bir vaqtda **bir nechta guruhda** ishlay oladi. Har bir guruhning **o'z oila jadvali** bor:
tabrik faqat o'sha guruh jadvalidagi inson uchun va faqat o'sha guruhga yuboriladi.

1. Botni oilaviy guruhga qo'shing va xabar yuborish ruxsatini bering.
2. Guruh ichida `/setgroup` yuboring — guruh ulanadi (boshqa guruhlar o'chirilmaydi).
3. Bot bilan shaxsiy chatda `/groups` — guruhni tugma orqali tanlang.
4. `/add`, `/birthdays`, `/edit` va boshqa komandalar **tanlangan guruh** jadvali bilan ishlaydi.
5. Guruh ichida `/birthdays`, `/today`, `/next`, `/upcoming` aynan shu guruh jadvalini ko'rsatadi.
6. Guruhni o'chirish: guruh ichida `/removegroup` (jadval saqlanib qoladi).
7. Insonni boshqa guruhga o'tkazish: kerakli guruhni tanlab, `/assign ID`.

- `.env` dagi `TARGET_GROUP_ID` faqat bazada birorta ham guruh bo'lmaganda birinchi guruh sifatida qo'shiladi.
- Superguruh ID si doim `-100` bilan boshlanadi. To'g'ri ID ni guruh ichida `/chatid` orqali bilib oling.
- Oddiy guruh superguruhga aylansa, bot yangi ID ni avtomatik saqlaydi (jadval yo'qolmaydi).

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
- `/groups` — guruhlar va guruhni tanlash
- `/setgroup` — guruhni ulash (guruh ichida)
- `/removegroup` — guruhni o'chirish (guruh ichida)
- `/assign ID` — insonni tanlangan guruhga o'tkazish
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

## 8. Tezlikni kuzatish
Har bir komanda qancha vaqtda bajarilgani logga yoziladi, sekinlari `(SEKIN)` belgisi bilan:

```powershell
docker logs -f family_birthday_bot | Select-String app.timing
```

- 1.5 soniyadan uzoq davom etgan komandalar va 1 soniyadan sekin Telegram API so'rovlari `WARNING` bo'lib chiqadi.
- Xabar matni (masalan, parol) logga yozilmaydi, faqat komanda nomi.
- Bitta token bilan faqat **bitta** bot nusxasi ishlashi kerak, aks holda `TelegramConflictError` va kechikishlar bo'ladi.

## Muhim
- Baza sxemasi ishga tushganda avtomatik yangilanadi (`init_db`), Docker'da esa avval `alembic upgrade head` bajariladi.
- Scheduler faqat bot ishlayotgan vaqtda ishlaydi.
- Administrator autentifikatsiyasi `ADMIN_USER_IDS` bilan cheklangan; bu qiymatni taxmin qilmang, o‘zingizning Telegram ID raqamingizni qo‘ying.
- Parol shaxsiy chatda kiritiladi. Telegram xabarini o‘chirishga ruxsat bermasa, bot o‘chirishni kafolatlay olmaydi.
- Tabrik va she’rlar hozircha lokal shablonlardan yaratiladi.
