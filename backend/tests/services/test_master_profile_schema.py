"""Tests für die CV-Builder-Erweiterungen des `MasterProfile`-Schemas (siehe
U1 des Plans: docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md).

Deckt zwei Dinge ab:
1. Die neuen Pydantic-Shapes (`SkillEntry`/`LanguageEntry`/`ProjectEntry`)
   validieren korrekt (KTD3: feste Werte-Skalen, Pflichtfelder).
2. Die Alembic-Migration `17c15ce91b4e` migriert bestehende
   `skills_json: list[str]`-Zeilen nach `list[{"name": ..., "level": ...}]`
   (KTD5), ohne Daten zu verlieren, und ist ein No-Op für bereits leere/
   bereits migrierte Zeilen.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.command import downgrade, upgrade
from alembic.config import Config
from pydantic import ValidationError

from app.schemas.master_profile import (
    LanguageEntry,
    MasterProfileBase,
    ProjectEntry,
    SkillEntry,
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI_PATH = _BACKEND_DIR / "alembic.ini"


# --- SkillEntry / LanguageEntry / ProjectEntry -----------------------------


def test_skill_entry_rejects_out_of_range_level() -> None:
    with pytest.raises(ValidationError):
        SkillEntry(name="Python", level="Meister")


def test_skill_entry_accepts_each_valid_level() -> None:
    for level in ("Grundkenntnisse", "Gut", "Sehr gut", "Experte"):
        entry = SkillEntry(name="Python", level=level)
        assert entry.level == level


def test_language_entry_rejects_out_of_range_level() -> None:
    with pytest.raises(ValidationError):
        LanguageEntry(name="Deutsch", level="Muttersprache")


def test_language_entry_accepts_each_cefr_level() -> None:
    for level in ("A1", "A2", "B1", "B2", "C1", "C2"):
        entry = LanguageEntry(name="Englisch", level=level)
        assert entry.level == level


def test_project_entry_requires_title_and_description() -> None:
    with pytest.raises(ValidationError):
        ProjectEntry(title="Portfolio-Website")  # description fehlt

    entry = ProjectEntry(title="Portfolio-Website", description="Persönliche Website mit React.")
    assert entry.title == "Portfolio-Website"
    assert entry.link is None


# --- MasterProfileBase.skills_json ------------------------------------------


def test_master_profile_base_round_trips_skills_json_as_skill_entries() -> None:
    profile = MasterProfileBase(
        full_name="Max Mustermann",
        email="max@example.com",
        skills_json=[{"name": "Python", "level": "Experte"}],
    )

    assert isinstance(profile.skills_json[0], SkillEntry)
    assert profile.skills_json[0].name == "Python"
    assert profile.skills_json[0].level == "Experte"


def test_master_profile_base_rejects_plain_string_skills_json() -> None:
    """Locks in the KTD3 shape change: `skills_json` is no longer
    `list[str]` - a bare string entry must fail validation, not silently
    round-trip."""
    with pytest.raises(ValidationError):
        MasterProfileBase(full_name="Max Mustermann", email="max@example.com", skills_json=["Python"])


# --- Migration 17c15ce91b4e: skills_json backfill ---------------------------


@pytest.fixture
def migration_db():
    """Frische SQLite-Datei, hochgezogen bis exakt VOR die neue Migration
    (`3cf25349329e`), damit Testzeilen im alten `list[str]`-Format eingefügt
    werden können, bevor `upgrade()` der neuen Migration läuft."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "migration-check.db"
        database_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, "3cf25349329e")

        engine = sa.create_engine(database_url)
        try:
            yield alembic_cfg, engine
        finally:
            engine.dispose()


def _insert_master_profile(engine: sa.Engine, **columns) -> None:
    defaults = dict(
        full_name="Max Mustermann",
        email="max@example.com",
        experiences_json="[]",
        education_json="[]",
        skills_json="[]",
    )
    defaults.update(columns)
    with engine.begin() as conn:
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(f":{key}" for key in defaults)
        conn.execute(sa.text(f"INSERT INTO master_profiles ({cols}) VALUES ({placeholders})"), defaults)


def test_migration_backfills_flat_skill_strings_to_leveled_entries(migration_db) -> None:
    alembic_cfg, engine = migration_db
    _insert_master_profile(engine, email="skills@example.com", skills_json='["Python", "SQL"]')

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT skills_json FROM master_profiles WHERE email = :email"),
            {"email": "skills@example.com"},
        ).fetchone()

    import json

    migrated = json.loads(row.skills_json)
    assert migrated == [
        {"name": "Python", "level": "Grundkenntnisse"},
        {"name": "SQL", "level": "Grundkenntnisse"},
    ]


def test_migration_handles_empty_skills_and_no_photo_or_language_data(migration_db) -> None:
    alembic_cfg, engine = migration_db
    _insert_master_profile(engine, email="empty@example.com", skills_json="[]")

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT skills_json, languages_json, projects_json, photo_path, "
                "photo_filename, template_id FROM master_profiles WHERE email = :email"
            ),
            {"email": "empty@example.com"},
        ).fetchone()

    import json

    assert json.loads(row.skills_json) == []
    assert json.loads(row.languages_json) == []
    assert json.loads(row.projects_json) == []
    assert row.photo_path is None
    assert row.photo_filename is None
    assert row.template_id is None


def test_migration_upgrade_downgrade_upgrade_round_trips(migration_db) -> None:
    alembic_cfg, engine = migration_db
    _insert_master_profile(engine, email="roundtrip@example.com", skills_json='["Python"]')

    upgrade(alembic_cfg, "head")
    downgrade(alembic_cfg, "-1")
    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT skills_json FROM master_profiles WHERE email = :email"),
            {"email": "roundtrip@example.com"},
        ).fetchone()

    import json

    assert json.loads(row.skills_json) == [{"name": "Python", "level": "Grundkenntnisse"}]
