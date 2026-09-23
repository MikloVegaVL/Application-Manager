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
    """Nach der U2-Revision darf der Graph genau EINEN Head haben - ein
    zweiter Head würde `alembic upgrade head` mit "Multiple head revisions"
    abbrechen lassen."""
    alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
    heads = ScriptDirectory.from_config(alembic_cfg).get_heads()

    assert len(heads) == 1, f"Erwartet genau einen Alembic-Head, gefunden: {heads}"
    assert "f71a8d3d7876" in heads


def test_automation_column_drop_migration_upgrades_and_downgrades() -> None:
    """U2-Testszenario: die neue Migration droppt auf einer frischen
    SQLite-DB die vier `Application`-Automationsspalten und fügt
    `portal_submissions.report_id` hinzu - vor UND wieder zurück."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "automation-drop-check.db"
        database_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, "head")

        application_columns = _table_columns(database_url, "applications")
        assert "automation_state" not in application_columns
        assert "action_needed_reason" not in application_columns
        assert "action_needed_detail" not in application_columns
        assert "automation_started_at" not in application_columns
        assert "report_id" in _table_columns(database_url, "portal_submissions")

        downgrade(alembic_cfg, "9c1d2e3f4a5b")

        restored_columns = _table_columns(database_url, "applications")
        assert "automation_state" in restored_columns
        assert "action_needed_reason" in restored_columns
        assert "action_needed_detail" in restored_columns
        assert "automation_started_at" in restored_columns
        assert "report_id" not in _table_columns(database_url, "portal_submissions")


def _table_columns(database_url: str, table_name: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return {column["name"] for column in inspect(connection).get_columns(table_name)}
    finally:
        engine.dispose()
