FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY media ./media
COPY alembic ./alembic
COPY alembic.ini .

# Avval baza sxemasi yangilanadi, keyin bot ishga tushadi.
CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
