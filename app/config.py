from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import datetime

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============================================================
    # TELEGRAM CONFIGURATION
    # ============================================================

    bot_token: str = Field(
        ...,
        alias="BOT_TOKEN",
        repr=False,
    )

    bot_access_password: str = Field(
        ...,
        alias="BOT_ACCESS_PASSWORD",
        repr=False,
    )

    target_group_id: int | None = Field(
        default=None,
        alias="TARGET_GROUP_ID",
    )

    admin_user_ids: str = Field(
        default="",
        alias="ADMIN_USER_IDS",
    )

    # ============================================================
    # DATABASE CONFIGURATION
    # ============================================================

    database_url: str = Field(
        ...,
        alias="DATABASE_URL",
        repr=False,
    )

    # ============================================================
    # SCHEDULER CONFIGURATION
    # ============================================================

    timezone: str = Field(
        default="Asia/Tashkent",
        alias="TIMEZONE",
    )

    birthday_reminder_time: str = Field(
        default="09:00",
        alias="BIRTHDAY_REMINDER_TIME",
    )

    leap_day_policy: str = Field(
        default="february_28",
        alias="LEAP_DAY_POLICY",
    )

    # ============================================================
    # LOGGING
    # ============================================================

    log_level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )

    # ============================================================
    # PYDANTIC SETTINGS
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        validate_default=True,
    )

    # ============================================================
    # VALIDATION
    # ============================================================

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("BOT_TOKEN bo'sh bo'lishi mumkin emas.")

        return value

    @field_validator("bot_access_password")
    @classmethod
    def validate_bot_access_password(cls, value: str) -> str:
        value = value.strip()

        if len(value) < 4:
            raise ValueError(
                "BOT_ACCESS_PASSWORD kamida 4 belgidan iborat bo'lishi kerak."
            )

        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("DATABASE_URL bo'sh bo'lishi mumkin emas.")

        if not value.startswith(
            ("postgresql://", "postgresql+asyncpg://")
        ):
            raise ValueError(
                "DATABASE_URL PostgreSQL uchun noto'g'ri formatda."
            )

        return value

    @field_validator("target_group_id", mode="before")
    @classmethod
    def empty_target_group_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None

        return value

    @field_validator("target_group_id")
    @classmethod
    def validate_target_group_id(
        cls,
        value: int | None,
    ) -> int | None:
        if value is None:
            return None

        if value == 0:
            raise ValueError("TARGET_GROUP_ID 0 bo'lishi mumkin emas.")

        if value > 0:
            # Guruh/superguruh ID'lari doim manfiy bo'ladi. Superguruh ID'si
            # "-100" prefiksi bilan boshlanadi (masalan: -1001234567890).
            raise ValueError(
                "TARGET_GROUP_ID manfiy bo'lishi kerak. Superguruh uchun "
                f"'-100' prefiksini qo'shing: -100{value}. To'g'ri ID'ni "
                "guruh ichida /chatid komandasi orqali bilib oling."
            )

        return value

    @field_validator("admin_user_ids")
    @classmethod
    def validate_admin_user_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            return value

        for item in value.split(","):
            item = item.strip()

            if not item:
                continue

            try:
                user_id = int(item)
            except ValueError:
                raise ValueError(
                    f"ADMIN_USER_IDS ichida noto'g'ri ID: {item}"
                )

            if user_id <= 0:
                raise ValueError(
                    f"Admin Telegram ID musbat bo'lishi kerak: {item}"
                )

        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = value.strip()

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"TIMEZONE noto'g'ri: {value}"
            )

        return value

    @field_validator("birthday_reminder_time")
    @classmethod
    def validate_reminder_time(cls, value: str) -> str:
        value = value.strip()

        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ValueError(
                "BIRTHDAY_REMINDER_TIME HH:MM formatida bo'lishi kerak. "
                "Masalan: 09:00"
            )

        return value

    @field_validator("leap_day_policy")
    @classmethod
    def validate_leap_day_policy(cls, value: str) -> str:
        value = value.strip().lower()

        allowed_values = {
            "february_28",
            "march_1",
        }

        if value not in allowed_values:
            raise ValueError(
                "LEAP_DAY_POLICY faqat "
                "'february_28' yoki 'march_1' bo'lishi mumkin."
            )

        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        value = value.strip().upper()

        allowed_levels = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }

        if value not in allowed_levels:
            raise ValueError(
                f"LOG_LEVEL noto'g'ri: {value}"
            )

        return value

    # ============================================================
    # ADMIN HELPERS
    # ============================================================

    @property
    def admin_ids(self) -> set[int]:
        return {
            int(item.strip())
            for item in self.admin_user_ids.split(",")
            if item.strip()
        }


# ================================================================
# SETTINGS INSTANCE
# ================================================================

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()