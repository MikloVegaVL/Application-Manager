"""Datenbank-Initialisierung: bringt das Schema beim App-Start auf den
aktuellen Stand.

Gegen PostgreSQL (Docker Compose / Produktivbetrieb) laufen jetzt echte
Alembic-Migrationen (`alembic upgrade head`, siehe `/backend/alembic`) statt
`Base.metadata.create_all()`. `create_all()` legt zwar fehlende Tabellen an,
fasst aber - wie hier zuvor dokumentiert - bereits bestehende Tabellen nicht
an: eine spätere Modelländerung (z. B. ein neues Spaltenfeld) landete dadurch
nie in einer bereits laufenden PostgreSQL-Datenbank. Genau das führte zu
einem `UndefinedColumn`-Fehler in `POST /applications/generate` und
`GET /profile` (ce-debug-Untersuchung, 2026-08-20: `MasterProfile.cv_file_path`
/`cv_filename` fehlten in der laufenden DB, obwohl im Modell längst
vorhanden - siehe `alembic/versions/c073e73561c1_baseline_schema.py`).

Für die lokale Entwicklung mit SQLite bleibt `create_all()` der Fallback:
dort ist die DB-Datei typischerweise wegwerfbar/lokal pro Entwickler, ein
Migrationslauf bringt dort keinen Mehrwert (siehe `app.db.database`s
Doku zu den drei DATABASE_URL-Szenarien).
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

# Der Import registriert alle Modelle in Base.metadata - ohne ihn wüsste
# weder create_all() noch Alembics Autogenerate etwas von JobOffer,
# MasterProfile und Application.
from app import models  # noqa: F401
from app.core.config import settings
from app.db.database import Base, engine, escape_for_alembic_config, is_sqlite_url

logger = logging.getLogger(__name__)

# Liegt neben diesem Modul in backend/alembic.ini - unabhängig vom
# Arbeitsverzeichnis, aus dem uvicorn gestartet wird.
_ALEMBIC_INI_PATH = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


def init_db() -> None:
    """Bringt das DB-Schema auf den aktuellen Stand: Alembic-Migrationen für
    PostgreSQL, `create_all()` als SQLite-Dev-Fallback."""
    if is_sqlite_url(settings.DATABASE_URL):
        logger.info("SQLite erkannt - initialisiere Datenbank-Tabellen via create_all() ...")
        Base.metadata.create_all(bind=engine)
        logger.info("Datenbank-Tabellen erfolgreich angelegt/geprüft.")
        return

    logger.info("Führe Alembic-Migrationen aus (DATABASE_URL=%s) ...", settings.DATABASE_URL)
    alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
    # set_main_option() schreibt in ein ConfigParser mit %-Interpolation - ein
    # Passwort mit wörtlichem % (z. B. urlencodete Sonderzeichen) würde sonst
    # sofort mit ValueError abstürzen, noch bevor eine Migration läuft (per
    # Review reproduziert). escape_for_alembic_config() entfaltet beim
    # Auslesen wieder korrekt zur ursprünglichen URL.
    alembic_cfg.set_main_option("sqlalchemy.url", escape_for_alembic_config(settings.DATABASE_URL))
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic-Migrationen erfolgreich angewendet.")
