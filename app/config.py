from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(default="postgresql+asyncpg://pvz:pvz@localhost:5432/pvz", alias="DATABASE_URL")
    timezone: str = Field(default="Europe/Moscow", alias="TIMEZONE")

    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")
    confirm_request_time: str = Field(default="19:00", alias="CONFIRM_REQUEST_TIME")

    google_service_account_file: Optional[str] = Field(default=None, alias="GOOGLE_SERVICE_ACCOUNT_FILE")
    google_main_sheet_id: Optional[str] = Field(default=None, alias="GOOGLE_MAIN_SHEET_ID")
    google_main_schedule_tab: str = Field(default="График", alias="GOOGLE_MAIN_SCHEDULE_TAB")
    google_main_stats_tab: str = Field(default="Статистика", alias="GOOGLE_MAIN_STATS_TAB")

    google_disputes_sheet_id: Optional[str] = Field(default=None, alias="GOOGLE_DISPUTES_SHEET_ID")
    google_disputes_tab: str = Field(default="Лист1", alias="GOOGLE_DISPUTES_TAB")

    google_ozon_sheet_id: Optional[str] = Field(default=None, alias="GOOGLE_OZON_SHEET_ID")
    google_ozon_tab: str = Field(default="Лист1", alias="GOOGLE_OZON_TAB")

    wb_workbook_file: Optional[str] = Field(default=None, alias="WB_WORKBOOK_FILE")
    wb_workbook_stats_sheet: str = Field(
        default="Статистика по выдаче и приёмке",
        alias="WB_WORKBOOK_STATS_SHEET",
    )

    # Шаблон кода подтверждения критических операций (если включите email-этап отдельно)
    critical_code: Optional[str] = Field(default=None, alias="CRITICAL_CODE")

    wb_issue_bonus_step: int = Field(default=100, alias="WB_ISSUE_BONUS_STEP")
    wb_issue_bonus_amount: int = Field(default=100, alias="WB_ISSUE_BONUS_AMOUNT")

    manager_bonus_1: int = Field(default=10000, alias="MANAGER_BONUS_1")
    manager_bonus_2: int = Field(default=5000, alias="MANAGER_BONUS_2")
    manager_bonus_3_per_ticket: int = Field(default=200, alias="MANAGER_BONUS_3_PER_TICKET")

    # Email (Yandex SMTP) — used for admin confirmation codes
    smtp_host: str = Field(default="smtp.yandex.ru", alias="SMTP_HOST")
    smtp_port: int = Field(default=465, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from: Optional[str] = Field(default=None, alias="SMTP_FROM")
    # TTL for email confirmation codes (minutes)
    email_code_ttl_minutes: int = Field(default=10, alias="EMAIL_CODE_TTL_MINUTES")

    # Web admin panel settings
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    web_secret_key: str = Field(default="change-me-in-production", alias="WEB_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")

    @property
    def admin_ids(self) -> list[int]:
        raw = self.admin_ids_raw
        if not raw or not raw.strip():
            return []
        return [int(v.strip()) for v in raw.split(",") if v.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
