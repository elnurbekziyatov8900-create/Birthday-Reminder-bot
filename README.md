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

`.env` ichidagi `DATABASE_URL` quyidagi shaklda bo‘lsin; parol `compose.yaml` dagi `POSTGRES_PASSWORD` bilan mos bo‘lishi kerak:

`postgresql+asyncpg://birthday_user:change_this_password@localhost:5437/birthday_db`

Production uchun `change_this_password` o‘rniga kuchli parol qo‘ying va compose muhitidagi parolni ham moslang.

## 4. Botni ishga tushirish

```powershell
python -m app.main
```

Bot bilan shaxsiy chatni oching, `/start` yuboring va `elnur` parolini kiriting. `ADMIN_USER_IDS` ichida aynan sizning Telegram user ID raqamingiz bo‘lishi shart.

## 5. Guruhni ulash
1. Botni oilaviy guruhga qo‘shing.
2. Botga xabar yuborish ruxsatini bering.
3. Guruh ichida `/setgroup` yuboring.
4. `.env` dagi `TARGET_GROUP_ID` bo‘sh qolsa ham, `/setgroup` saqlagan guruh ishlatiladi.

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
- `/delete ID` — insonni arxivlash
- `/status` — holat
- `/cancel` — dialogni bekor qilish

## Muhim
- Birinchi ishga tushirishda jadvallar SQLAlchemy orqali yaratiladi. Kengaytirilgan ishlab chiqarish muhitida Alembic migratsiyalarini qo‘shish tavsiya qilinadi.
- Scheduler faqat bot ishlayotgan vaqtda ishlaydi.
- Hozirgi `/edit` handler yo‘riqnoma beradi; to‘liq tahrirlash dialogi keyingi iteratsiyada qo‘shiladi.
- Administrator autentifikatsiyasi `ADMIN_USER_IDS` bilan cheklangan; bu qiymatni taxmin qilmang, o‘zingizning Telegram ID raqamingizni qo‘ying.
- Parol shaxsiy chatda kiritiladi. Telegram xabarini o‘chirishga ruxsat bermasa, bot o‘chirishni kafolatlay olmaydi.
- Tabrik va she’rlar hozircha lokal shablonlardan yaratiladi.
