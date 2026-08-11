"""Zentrale Anwendungskonfiguration.

Liest Umgebungsvariablen (aus `.env` oder der Prozessumgebung) via
pydantic-settings ein. Damit steht eine typsichere, zentrale `settings`-
Instanz zur Verfügung, die im gesamten Backend importiert werden kann.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Anwendungsweite Einstellungen, befüllt aus Umgebungsvariablen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Allgemein ---
    APP_NAME: str = "Application Manager"
    API_V1_PREFIX: str = "/api"
    ENVIRONMENT: str = "development"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:4200"]

    # --- Datenbank ---
    DATABASE_URL: str = "sqlite:///./app.db"

    # --- OpenAI / LLM ---
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o"

    # --- SMTP / Mailversand ---
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str | None = None

    # --- Arbeitsagentur API ---
    ARBEITSAGENTUR_CLIENT_ID: str | None = None
    ARBEITSAGENTUR_CLIENT_SECRET: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Gecachte Settings-Instanz (wird nur einmal pro Prozess eingelesen)."""
    return Settings()


settings = get_settings()
