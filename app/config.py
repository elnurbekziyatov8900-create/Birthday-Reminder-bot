from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    bot_access_password: str = Field(default="elnur", alias="BOT_ACCESS_PASSWORD")
    database_url: str = Field(alias="DATABASE_URL")
    target_group_id: int | None = Field(default=None, alias="TARGET_GROUP_ID")
    admin_user_ids: str = Field(default="", alias="ADMIN_USER_IDS")
    timezone: str = Field(default="Asia/Tashkent", alias="TIMEZONE")
    birthday_reminder_time: str = Field(default="09:00", alias="BIRTHDAY_REMINDER_TIME")
    leap_day_policy: str = Field(default="february_28", alias="LEAP_DAY_POLICY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def admin_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_user_ids.split(",") if x.strip()}

@lru_cache
def get_settings() -> Settings:
    return Settings()
