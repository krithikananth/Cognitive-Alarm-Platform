"""
Application configuration — SQLite mode for immediate local development.
Switch to PostgreSQL by changing DATABASE_URL when Docker databases are available.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ─── App ───
    APP_NAME: str = "Intelligent Cognitive Alarm Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ─── Database (SQLite — no Docker needed) ───
    DATABASE_URL: str = "sqlite+aiosqlite:///./cognitive_alarm.db"
    DATABASE_URL_SYNC: str = "sqlite:///./cognitive_alarm.db"
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "cognitive_alarm_challenges"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ─── Feature Flags ───
    USE_MONGODB: bool = False
    USE_REDIS: bool = False

    # ─── Authentication ───
    SECRET_KEY: str = "super-secret-key-change-in-production-ica-platform-2024"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ─── OAuth2 ───
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # ─── CORS ───
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


settings = Settings()
