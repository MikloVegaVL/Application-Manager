"""Regression: hält Alembic-Migrationen und ORM-Modelle in Sync.

Bis 2026-08-20 gab es zwar ein `alembic`-Verzeichnis, aber keine einzige
Migration - `Base.metadata.create_all()` (siehe `app.db.init_db`) war die
einzige Schema-Quelle, und `create_all()` fasst bereits existierende
Tabellen nicht an. Als `MasterProfile.cv_file_path`/`cv_filename` zum Modell
hinzukamen, landeten die Spalten dadurch nie in der bereits laufenden
PostgreSQL-Datenbank: `POST /applications/generate` und `GET /profile`
schlugen mit `UndefinedColumn` fehl, sobald sie `MasterProfile` abfragten
(ce-debug-Untersuchung, 2026-08-20).

Dieser Test lässt `alembic upgrade head` gegen eine frische SQLite-Datei
laufen und vergleicht das Ergebnis per `compare_metadata` mit
`Base.metadata` - genau der Mechanismus, den `alembic revision
--autogenerate` intern nutzt. Ein Diff heißt: ein Modellfeld hat keine
zugehörige Migration (oder umgekehrt) - exakt der Fehler, der zu diesem Bug
führte.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.command import downgrade, upgrade
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401 - registriert alle Modelle in Base.metadata
from app.db.database import Base

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ALEMBIC_INI_PATH = _BACKEND_DIR / "alembic.ini"


def test_alembic_migrations_match_current_models() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "migration-check.db"
        database_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, "head")

        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                # compare_server_default: Alembics Default-Vergleich lässt
                # server_default sonst außen vor (per Review aufgezeigt) - ein
                # künftiger Server-Default, der zwischen Modell und Migration
                # abweicht, würde sonst unbemerkt bleiben, obwohl bereits
                # eingefügte Zeilen den falschen Default-Wert bekämen.
                migration_context = MigrationContext.configure(
                    connection, opts={"compare_server_default": True}
                )
                diff = compare_metadata(migration_context, Base.metadata)
        finally:
            engine.dispose()

    assert diff == [], (
        "Modelle und Alembic-Migrationen sind nicht mehr synchron - fehlt eine "
        f"neue Migration (`alembic revision --autogenerate`)? Diff: {diff}"
    )


def test_alembic_has_a_single_head() -> None:
    """Nach der neuen U7-Revision darf der Graph genau EINEN Head haben -
    ein zweiter Head würde `alembic upgrade head` mit "Multiple head
    revisions" abbrechen lassen."""
    alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
    heads = ScriptDirectory.from_config(alembic_cfg).get_heads()

    assert len(heads) == 1, f"Erwartet genau einen Alembic-Head, gefunden: {heads}"
    assert "9c1d2e3f4a5b" in heads


def test_action_needed_detail_migration_upgrades_and_downgrades() -> None:
    """U7-Testszenario: die neue `action_needed_detail`-Migration läuft auf
    einer frischen SQLite-DB vor UND wieder zurück."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "action-needed-detail-check.db"
        database_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, "head")

        assert "action_needed_detail" in _application_columns(database_url)

        downgrade(alembic_cfg, "a41edaf603a3")

        assert "action_needed_detail" not in _application_columns(database_url)


def _application_columns(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return {column["name"] for column in inspect(connection).get_columns("applications")}
    finally:
        engine.dispose()
