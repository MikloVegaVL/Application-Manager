"""Zentrale Anwendungskonfiguration.

Liest Umgebungsvariablen (aus `.env` oder der Prozessumgebung) via
pydantic-settings ein. Damit steht eine typsichere, zentrale `settings`-
Instanz zur Verfügung, die im gesamten Backend importiert werden kann.
"""
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ablageort des persistenten Portal-Fill-Secrets. `generated/` ist bereits als
# Docker-Volume gebunden (siehe `docker-compose.yml`) und gitignored, damit das
# Secret Neustarts übersteht und vom Nutzer aus der Datei gelesen werden kann
# (KTD13).
PORTAL_FILL_SECRET_FILE = Path("generated/portal_fill_secret")


def _load_or_create_portal_fill_secret() -> str:
    """Liest das Portal-Fill-Secret aus `PORTAL_FILL_SECRET_FILE` oder erzeugt
    es beim ersten Start und persistiert es, damit es über Neustarts stabil
    bleibt (KTD13).

    Wird nur aufgerufen, wenn `PORTAL_FILL_SECRET` nicht gesetzt ist - ein
    `.env`-Wert hat weiterhin Vorrang.
    """
    try:
        if PORTAL_FILL_SECRET_FILE.exists():
            existing = PORTAL_FILL_SECRET_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
    except OSError:
        # Nicht lesbar - unten wird neu erzeugt.
        pass

    secret = secrets.token_urlsafe(32)
    try:
        PORTAL_FILL_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORTAL_FILL_SECRET_FILE.write_text(secret + "\n", encoding="utf-8")
        PORTAL_FILL_SECRET_FILE.chmod(0o600)
    except OSError:
        # Nicht schreibbar (z. B. read-only FS): das Secret gilt trotzdem für
        # diesen Prozess, ist dann aber nicht über Neustarts stabil.
        pass
    return secret


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
    # War zuvor 120.0, dann 300.0 - auf CPU-only Ollama (kein GPU-Passthrough
    # im Docker-Setup) ist schema-eingeschränkte Generierung nicht nur
    # langsam (~2.2 Token/s), sondern auch spürbar UNGLEICHMÄSSIG: bei der
    # ce-debug-Untersuchung zur Bewerbungsgenerierung (ai_generator.py, nutzt
    # weiterhin qwen2.5:7b-instruct - ein kleineres Modell lieferte für
    # Anschreiben spürbar schlechtere Prosequalität, siehe Commit-Historie)
    # brauchten zwei erfolgreiche Läufe für dieselbe echte Bewerberin/Stelle
    # 228s bzw. 259s, ein dritter Lauf überschritt 300s klar. Auch die CV-
    # Analyse (qwen2.5:3b-instruct, sonst 108-246s) überschritt bei einem
    # Lauf gegen eine reale, echte CV-PDF ebenfalls 300s, obwohl ein exakt
    # identischer Wiederholungslauf nur 141s brauchte - reine Lauf-zu-Lauf-
    # Varianz auf CPU-only Hardware, kein Datenproblem. 600s gibt selbst dem
    # langsameren 7b-Modell realistisch Zeit inkl. Spielraum für diese
    # Varianz - `frontend/nginx.conf`s `proxy_read_timeout` MUSS deutlich
    # darüber liegen, da `generate_structured` bis zu drei sequentielle
    # Aufrufe machen kann (Erstversuch + Retry + Abflach-Fallback).
    OLLAMA_TIMEOUT_SECONDS: float = 600.0

    # --- SMTP / Mailversand ---
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str | None = None

    # --- Zweiter SMTP-Account (sayhello@thomastritscher.com, All-Inkl/KAS) ---
    # `app.services.mail_service` wählt diesen Account statt des obigen
    # Primär-Accounts, wenn `MasterProfile.sender_email` dieser Adresse
    # entspricht - so landet die Mail tatsächlich im Sent-Ordner dieses
    # Postfachs, statt nur den From-Header eines fremden Accounts zu tragen.
    # Port 465 bei All-Inkl ist implizites SSL (kein STARTTLS), daher ein
    # eigenes `SMTP2_USE_SSL` statt des `SMTP_USE_TLS` des Primär-Accounts.
    SMTP2_HOST: str | None = None
    SMTP2_PORT: int = 465
    SMTP2_USERNAME: str | None = None
    SMTP2_PASSWORD: str | None = None
    SMTP2_USE_SSL: bool = True
    SMTP2_FROM_EMAIL: str | None = None

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

    # --- Jobsuche: weitere HTML-Boards (U3/U6, KTD7) ---
    # Alle neuen Börsen sind standardmäßig aktiviert; ein Board ohne
    # verlässliche anonyme Suchoberfläche lässt sich per Flag deaktivieren,
    # ohne den Rest der Suche zu blockieren (KD1).
    JOB_SEARCH_DEVJOBS_ENABLED: bool = True
    JOB_SEARCH_PROGRAMMIERERJOBBOERSE_ENABLED: bool = True

    # --- Jobsuche: credential-basierte APIs (siehe Plan
    # docs/plans/2026-09-15-003-feat-job-search-source-and-relevance-plan.md) ---
    JOB_SEARCH_ADZUNA_ENABLED: bool = True
    JOB_SEARCH_JOOBLE_ENABLED: bool = True
    # Leere Defaults sind beabsichtigt: ohne Zugangsdaten melden Adzuna und
    # Jooble den Status `not-configured`, statt die Suche fehlschlagen zu
    # lassen.
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""
    # Regionsgebunden: ein auf `jooble.org` erzeugter Key liefert nur
    # US-Stellen - für den deutschen Markt den Key auf
    # https://de.jooble.org/api/about registrieren (siehe jooble.py).
    JOOBLE_API_KEY: str = ""

    # --- Bewerbungs-E-Mail-Suche (On-Demand, KTD3/KTD4) ---
    # Die Suche ist eine synchrone Live-Scrape-Anfrage und muss laut KTD4
    # strikt begrenzt sein: Seitenanzahl, Per-Fetch-Timeout, maximale
    # Body-Größe, an die Extraktion gegebener Seitentext und eine
    # Gesamt-Deadline. Die Deadline liegt bewusst deutlich unter
    # `frontend/nginx.conf`s `proxy_read_timeout` (2000s, siehe dort), damit
    # die Anfrage immer auflöst statt in einen Proxy-Timeout zu laufen. Die
    # Adressen liest eine Regex (kein LLM - siehe Service-Docstring).
    APPLICATION_EMAIL_LOOKUP_MAX_PAGES: int = 6
    APPLICATION_EMAIL_LOOKUP_FETCH_TIMEOUT_SECONDS: float = 10.0
    APPLICATION_EMAIL_LOOKUP_MAX_BODY_BYTES: int = 400_000
    # Spiegelt `ai_generator._MAX_JOB_DESCRIPTION_CHARS` (Token-/Kosten-Schutz).
    APPLICATION_EMAIL_LOOKUP_MAX_PAGE_TEXT_CHARS: int = 6_000
    APPLICATION_EMAIL_LOOKUP_DEADLINE_SECONDS: float = 45.0

    # --- Portal-Fill (Browser-Erweiterung, KTD13) ---
    # Hoch-entropisches Shared Secret, das jede erweiterungsseitige
    # `/portal-fill/*`-Route als Header verlangt (KTD13). Ist es beim Start
    # nicht gesetzt, liest `_load_or_create_portal_fill_secret` es aus
    # `PORTAL_FILL_SECRET_FILE` oder erzeugt es beim ersten Start und
    # persistiert es - dadurch bleibt es über Neustarts stabil und muss nur
    # EINMAL in die Options-Seite der Erweiterung kopiert werden. Der Wert
    # steht auf dem Host in `backend/generated/portal_fill_secret` (bzw. im
    # Container unter `/app/generated/portal_fill_secret`). Ein
    # `PORTAL_FILL_SECRET`-Wert in `.env` hat weiterhin Vorrang.
    PORTAL_FILL_SECRET: str = Field(default_factory=_load_or_create_portal_fill_secret)

    # --- Generierte/hochgeladene Dateien ---
    # Ablageort der vom Nutzer hochgeladenen Lebenslauf-Anhang-Datei (siehe
    # `app.api.profile`). Es gibt keine serverseitig generierten Bewerbungs-
    # PDFs mehr - die KI generiert nur noch den Anschreiben-Text, der
    # Lebenslauf wird vom Nutzer als Datei hochgeladen und unverändert als
    # E-Mail-Anhang versendet.
    PROFILE_FILES_DIR: str = "generated/profile"


@lru_cache
def get_settings() -> Settings:
    """Gecachte Settings-Instanz (wird nur einmal pro Prozess eingelesen)."""
    return Settings()


settings = get_settings()
