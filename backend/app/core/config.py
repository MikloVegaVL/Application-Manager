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

    # --- Ollama / LLM ---
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    # Allgemeiner Default (aktuell nur von der Bewerbungstext-Generierung in
    # ai_generator.py genutzt).
    OLLAMA_MODEL: str = "qwen2.5:7b-instruct"
    # Eigenes, kleineres Modell nur für die CV-Analyse (siehe
    # ce-debug-Untersuchung, 2026-08-18): qwen2.5:7b-instruct lief unter
    # schema-eingeschränkter Generierung auf CPU-only Ollama regelmäßig in
    # einen Timeout (~2.2 Token/s, ein normaler mehrseitiger Lebenslauf
    # brauchte >300s). qwen2.5:3b-instruct wurde live gegen echte, mehrseitige
    # Test-Lebensläufe UND den echten `_SYSTEM_PROMPT` aus pdf_parser.py
    # geprüft: vollständige, korrekte Extraktion (alle Erfahrungs-/
    # Ausbildungs-/Skill-Einträge) in 108-246s statt eines Timeouts. Bewusst
    # NICHT als neuer `OLLAMA_MODEL`-Default gesetzt, da diese Prüfung nur die
    # CV-Analyse abdeckt, nicht die Bewerbungstext-Generierung - ein globaler
    # Wechsel hätte deren Qualität ungetestet mitverändert.
    OLLAMA_MODEL_CV_PARSING: str = "qwen2.5:3b-instruct"
    # War zuvor 120.0 - auf CPU-only Ollama (kein GPU-Passthrough im Docker-
    # Setup, siehe ce-debug-Untersuchung, 2026-08-18) misst schema-
    # eingeschränkte Generierung (jeder generate_structured-Aufruf, auch die
    # CV-Analyse) nur ~2.2 Token/s - ein echter mehrseitiger Lebenslauf
    # brauchte damit regelmäßig länger als 120s und lief in einen Timeout
    # (bestätigt per Live-Reproduktion und echten Backend-Logs). 300s gibt
    # einem einzelnen Ollama-Aufruf realistisch Zeit zum Fertigwerden -
    # `frontend/nginx.conf`s `proxy_read_timeout` MUSS deutlich darüber
    # liegen, da `generate_structured` bis zu drei sequentielle Aufrufe
    # machen kann (Erstversuch + Retry + Abflach-Fallback).
    OLLAMA_TIMEOUT_SECONDS: float = 300.0

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

    # --- Jobsuche: LinkedIn / Xing (siehe KTD8 im Plan) ---
    JOB_SEARCH_LINKEDIN_ENABLED: bool = True
    JOB_SEARCH_XING_ENABLED: bool = True
    # Wie lange JobSearchService.search() maximal auf alle drei Quellen
    # wartet, bevor eine noch offene Quelle als "unavailable" (timeout)
    # markiert wird (KTD1).
    JOB_SEARCH_DEADLINE_SECONDS: float = 12.0
    # Wie viele Ergebnisse LinkedIns Guest-Endpunkt pro Suche liefern soll -
    # begrenzt, wie schnell das anonyme Rate-Limit-Budget (~10 Seiten) aufgebraucht wird.
    JOB_SEARCH_LINKEDIN_RESULT_CAP: int = 10
    # Wie lange LinkedIn nach einem 429 übersprungen wird (KTD5).
    JOB_SEARCH_LINKEDIN_COOLDOWN_SECONDS: float = 300.0

    # --- Generierte Dateien (Bewerbungs-PDFs) ---
    GENERATED_FILES_DIR: str = "generated/applications"


@lru_cache
def get_settings() -> Settings:
    """Gecachte Settings-Instanz (wird nur einmal pro Prozess eingelesen)."""
    return Settings()


settings = get_settings()
