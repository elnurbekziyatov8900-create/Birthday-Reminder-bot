from datetime import datetime, date
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(500))
    music_file_id: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class AuthUser(Base):
    __tablename__ = "auth_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    is_authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(30), default="admin")
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    birthday_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="sent")
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("person_id", "birthday_year", name="uq_person_birthday_year"),)

class GroupConfig(Base):
    __tablename__ = "group_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    title: Mapped[str] = mapped_column(String(255), default="Family group")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Tashkent")
    reminder_time: Mapped[str] = mapped_column(String(5), default="09:00")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
