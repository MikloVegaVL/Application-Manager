"""Tests für die CV-Builder-Erweiterungen des `MasterProfile`-Schemas (siehe
U1 des Plans: docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md).

Deckt zwei Dinge ab:
1. Die neuen Pydantic-Shapes (`SkillEntry`/`LanguageEntry`/`ProjectEntry`)
   validieren korrekt (KTD3: feste Werte-Skalen, Pflichtfelder).
2. Die Alembic-Migration `17c15ce91b4e` migriert bestehende
   `skills_json: list[str]`-Zeilen nach `list[{"name": ..., "level": ...}]`
   (KTD5), ohne Daten zu verlieren, und ist ein No-Op für bereits leere/
   bereits migrierte Zeilen.

Am Ende der Datei: Tests für U1 des Profil-Typen-Plans (docs/plans/2026-09-
23-001-feat-profile-types-plan.md) - Migration `f71a8d3d7876` fügt
`master_profiles.profile_type` (unique) und `applications.profile_id` (FK,
mit Backfill für bereits generierte Bewerbungen) hinzu und droppt
`master_profiles.email`s altes `unique=True`.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.command import downgrade, upgrade
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.master_profile import MasterProfile
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


def test_skill_entry_silently_ignores_a_legacy_category_key() -> None:
    """R9/AE6: Skill-Kategorie wurde aus dem Produkt entfernt (Session-
    Entscheidung, CV-Template-Erweiterungs-Plan 2026-09-13). Bereits
    gespeicherte Zeilen mit einem `category`-Schlüssel (Altdaten von vor der
    Entfernung) müssen weiterhin klaglos laden - Pydantics Default-Verhalten
    (`extra` nicht gesetzt = ignorieren) verwirft das unbekannte Feld, statt
    einen Validierungsfehler auszulösen oder es aufzubewahren."""
    entry = SkillEntry.model_validate({"name": "Python", "level": "Experte", "category": "Frontend"})

    assert entry.name == "Python"
    assert entry.level == "Experte"
    assert not hasattr(entry, "category")


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


def test_master_profile_base_no_longer_has_document_language() -> None:
    """U2/KTD3: das per-Profil-Feld `document_language` ist entfernt."""
    profile = MasterProfileBase(full_name="Max Mustermann", email="max@example.com")

    assert not hasattr(profile, "document_language")


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
    # Explizites Ziel statt `downgrade(cfg, "-1")`: "head" ist ein Merge-Punkt
    # (siehe `d98463c22408`), von dort ist "ein Schritt zurück" mehrdeutig.
    downgrade(alembic_cfg, "3cf25349329e")
    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT skills_json FROM master_profiles WHERE email = :email"),
            {"email": "roundtrip@example.com"},
        ).fetchone()

    import json

    assert json.loads(row.skills_json) == [{"name": "Python", "level": "Grundkenntnisse"}]


def test_migration_adds_content_language_and_drops_document_language(migration_db) -> None:
    """U1/U2 (Global Language Unification): revision `9a7b6c5d4e3f` fügt
    `content_language`/`content_translations_json` hinzu und entfernt das
    per-Profil-`document_language`. Bestehende Zeilen gelten als deutsch
    (`content_language='de'`, leerer Snapshot); der Downgrade stellt
    `document_language` wieder her und entfernt die neuen Spalten. Zielt
    bewusst auf `9a7b6c5d4e3f` statt `head`: die spätere Revision
    `581736b96da4` (Remove Translation Functionality, U4) entfernt
    `content_language`/`content_translations_json` wieder - siehe
    `test_migration_drops_content_language_columns` unten."""
    alembic_cfg, engine = migration_db
    _insert_master_profile(engine, email="language@example.com", skills_json="[]")

    upgrade(alembic_cfg, "9a7b6c5d4e3f")

    with engine.connect() as conn:
        columns_after_upgrade = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
        row = conn.execute(
            sa.text(
                "SELECT content_language, content_translations_json FROM master_profiles "
                "WHERE email = :email"
            ),
            {"email": "language@example.com"},
        ).fetchone()

    assert "content_language" in columns_after_upgrade
    assert "content_translations_json" in columns_after_upgrade
    assert "document_language" not in columns_after_upgrade
    assert row.content_language == "de"
    import json

    assert json.loads(row.content_translations_json) == {}

    # Nur die neue Revision zurückrollen: content-Spalten weg,
    # document_language wieder da (nullable, ohne Wert).
    downgrade(alembic_cfg, "e2b7c9a41f60")

    with engine.connect() as conn:
        columns_after_downgrade = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
        row_after_downgrade = conn.execute(
            sa.text("SELECT document_language FROM master_profiles WHERE email = :email"),
            {"email": "language@example.com"},
        ).fetchone()

    assert "content_language" not in columns_after_downgrade
    assert "content_translations_json" not in columns_after_downgrade
    assert "document_language" in columns_after_downgrade
    assert row_after_downgrade.document_language is None


def test_migration_content_language_upgrade_downgrade_upgrade_round_trips(migration_db) -> None:
    """U1: der vollständige Round-Trip 9a7b6c5d4e3f -> e2b7c9a41f60 ->
    9a7b6c5d4e3f ist idempotent (Guards in `upgrade`/`downgrade`), ohne Daten
    zu verlieren."""
    alembic_cfg, engine = migration_db
    _insert_master_profile(engine, email="roundtrip-content@example.com", skills_json="[]")

    upgrade(alembic_cfg, "9a7b6c5d4e3f")
    downgrade(alembic_cfg, "e2b7c9a41f60")
    upgrade(alembic_cfg, "9a7b6c5d4e3f")

    with engine.connect() as conn:
        columns = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
        row = conn.execute(
            sa.text("SELECT content_language FROM master_profiles WHERE email = :email"),
            {"email": "roundtrip-content@example.com"},
        ).fetchone()

    assert "content_language" in columns
    assert "content_translations_json" in columns
    assert "document_language" not in columns
    assert row.content_language == "de"


# --- Revision 581736b96da4: drops content_language/content_translations_json
# (U4, Remove Translation Functionality plan, 2026-09-13) -------------------


def test_migration_drops_content_language_columns(migration_db) -> None:
    """U4/R5/AE4: `head` no longer has `content_language`/
    `content_translations_json` - the app runs English-only now, there's no
    per-language content left to store. Downgrading back to `581736b96da4`
    (the revision that dropped them) re-adds both columns with their
    original shape - targeted explicitly rather than via `-1`, so this stays
    correct as later migrations (e.g. `f47e23403358`) move `head` further."""
    alembic_cfg, engine = migration_db
    _insert_master_profile(engine, email="drop-content-language@example.com", skills_json="[]")

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        columns_after_upgrade = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}

    assert "content_language" not in columns_after_upgrade
    assert "content_translations_json" not in columns_after_upgrade

    downgrade(alembic_cfg, "9a7b6c5d4e3f")

    with engine.connect() as conn:
        columns_after_downgrade = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
        row = conn.execute(
            sa.text(
                "SELECT content_language, content_translations_json FROM master_profiles "
                "WHERE email = :email"
            ),
            {"email": "drop-content-language@example.com"},
        ).fetchone()

    assert "content_language" in columns_after_downgrade
    assert "content_translations_json" in columns_after_downgrade
    assert row.content_language == "de"

    import json

    assert json.loads(row.content_translations_json) == {}

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        columns_after_reupgrade = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}

    assert "content_language" not in columns_after_reupgrade
    assert "content_translations_json" not in columns_after_reupgrade


# --- Merge revision d98463c22408: heals a database stuck on one sibling ----
#
# ce-debug, 2026-09-12: `17c15ce91b4e` (add cv builder fields) and
# `7b2f5c9d1a34` (add sent_to_email to applications) both branch
# independently off `3cf25349329e`. A database that ran `alembic upgrade
# head` while only `7b2f5c9d1a34` existed as a head - i.e. it walked that
# branch and stopped, never seeing `17c15ce91b4e` - must still receive
# `17c15ce91b4e`'s DDL once the merge revision `d98463c22408` joins both
# branches. This was previously broken by rebasing `7b2f5c9d1a34` onto
# `17c15ce91b4e` instead of using a real merge revision: `alembic upgrade
# head` then saw the stamped `7b2f5c9d1a34` as already being the head and
# silently skipped `17c15ce91b4e` entirely (reproduced live against a
# docker-compose Postgres database). Only manually verified until now -
# this pins it as an automated regression.


def test_merge_revision_heals_a_database_stuck_on_only_the_sent_to_email_branch(migration_db) -> None:
    alembic_cfg, engine = migration_db

    # Walks ONLY the sent_to_email branch, mirroring a database that ran
    # `alembic upgrade head` back when that revision was itself a head -
    # never touching the sibling `17c15ce91b4e` branch at all.
    upgrade(alembic_cfg, "7b2f5c9d1a34")

    with engine.connect() as conn:
        columns_before = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
    assert "languages_json" not in columns_before, "test setup must reproduce the pre-merge, single-branch state"

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        master_profile_columns = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
        application_columns = {col["name"] for col in sa.inspect(conn).get_columns("applications")}

    # The previously-missing sibling branch's DDL is now present ...
    for column in ("photo_path", "photo_filename", "languages_json", "projects_json", "template_id"):
        assert column in master_profile_columns
    # ... without losing the already-applied branch's DDL.
    assert "sent_to_email" in application_columns


# --- Migration c3d5e7f9a1b2: modern -> template-1 remap ---------------------
#
# Anders als `test_migrations.py` (nur Schema-Vergleich auf einer leeren DB)
# prüfen diese Tests den Daten-Remap auf einer bereits migrierten Datenbank,
# wie sie in Produktion existiert (Zeile mit `template_id='modern'`).


def _fresh_db_at(tmp_path: Path, revision: str) -> tuple[Config, sa.Engine]:
    database_url = f"sqlite:///{tmp_path / 'remap-check.db'}"
    alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    upgrade(alembic_cfg, revision)
    return alembic_cfg, sa.create_engine(database_url)


def test_migration_remaps_legacy_modern_template_id(tmp_path) -> None:
    alembic_cfg, engine = _fresh_db_at(tmp_path, "d98463c22408")
    try:
        _insert_master_profile(
            engine,
            email="modern@example.com",
            template_id="modern",
            languages_json="[]",
            projects_json="[]",
        )
        _insert_master_profile(
            engine,
            email="unset@example.com",
            template_id=None,
            languages_json="[]",
            projects_json="[]",
        )
        _insert_master_profile(
            engine,
            email="classic@example.com",
            template_id="classic",
            languages_json="[]",
            projects_json="[]",
        )

        upgrade(alembic_cfg, "head")

        with engine.connect() as conn:
            modern_row = conn.execute(
                sa.text("SELECT template_id FROM master_profiles WHERE email = :email"),
                {"email": "modern@example.com"},
            ).fetchone()
            unset_row = conn.execute(
                sa.text("SELECT template_id FROM master_profiles WHERE email = :email"),
                {"email": "unset@example.com"},
            ).fetchone()
            classic_row = conn.execute(
                sa.text("SELECT template_id FROM master_profiles WHERE email = :email"),
                {"email": "classic@example.com"},
            ).fetchone()

        assert modern_row.template_id == "template-1"
        assert unset_row.template_id is None
        # Ein echter, bereits gültiger Wert darf nicht mit-remappt werden.
        assert classic_row.template_id == "classic"
    finally:
        engine.dispose()


def test_remap_downgrade_does_not_revert_a_genuine_template_1(tmp_path) -> None:
    alembic_cfg, engine = _fresh_db_at(tmp_path, "d98463c22408")
    try:
        _insert_master_profile(
            engine,
            email="genuine@example.com",
            template_id="template-1",
            languages_json="[]",
            projects_json="[]",
        )
        upgrade(alembic_cfg, "head")

        # No-op-Downgrade der Remap-Migration: eine echte Auswahl bleibt erhalten.
        downgrade(alembic_cfg, "b8f2a4c6d9e1")

        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT template_id FROM master_profiles WHERE email = :email"),
                {"email": "genuine@example.com"},
            ).fetchone()

        assert row.template_id == "template-1"
    finally:
        engine.dispose()


# --- Migration f71a8d3d7876: profile_type + applications.profile_id --------
#
# U1, docs/plans/2026-09-23-001-feat-profile-types-plan.md.


@pytest.fixture
def previous_head_db():
    """Frische SQLite-Datei, hochgezogen bis exakt VOR die neue Migration
    (auf den vorherigen Single-Head `d1a2b3c4e5f6`), damit Testzeilen im
    Alt-Schema (kein `profile_type`/`profile_id`, `email` noch unique)
    eingefügt werden können, bevor `upgrade()` der neuen Migration läuft."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "profile-type-migration-check.db"
        database_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, "d1a2b3c4e5f6")

        engine = sa.create_engine(database_url)
        try:
            yield alembic_cfg, engine
        finally:
            engine.dispose()


def _insert_master_profile_pre_migration(engine: sa.Engine, **columns) -> int:
    defaults = dict(
        full_name="Max Mustermann",
        email="max@example.com",
        experiences_json="[]",
        education_json="[]",
        skills_json="[]",
        languages_json="[]",
        projects_json="[]",
    )
    defaults.update(columns)
    with engine.begin() as conn:
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(f":{key}" for key in defaults)
        result = conn.execute(
            sa.text(f"INSERT INTO master_profiles ({cols}) VALUES ({placeholders})"), defaults
        )
        return result.lastrowid


def _insert_job_offer(engine: sa.Engine, **columns) -> int:
    defaults = dict(
        title="Backend Engineer",
        company="Acme",
        source_url=f"https://example.com/jobs/{uuid.uuid4()}",
        source_platform="manual",
        is_processed=False,
    )
    defaults.update(columns)
    with engine.begin() as conn:
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(f":{key}" for key in defaults)
        result = conn.execute(
            sa.text(f"INSERT INTO job_offers ({cols}) VALUES ({placeholders})"), defaults
        )
        return result.lastrowid


def _insert_application(engine: sa.Engine, job_offer_id: int, **columns) -> int:
    defaults = dict(job_offer_id=job_offer_id, status="draft", cover_letter_text=None)
    defaults.update(columns)
    with engine.begin() as conn:
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(f":{key}" for key in defaults)
        result = conn.execute(
            sa.text(f"INSERT INTO applications ({cols}) VALUES ({placeholders})"), defaults
        )
        return result.lastrowid


def test_migration_adds_profile_type_and_profile_id_columns(previous_head_db) -> None:
    alembic_cfg, engine = previous_head_db

    upgrade(alembic_cfg, "head")

    profile_columns = {col["name"] for col in sa.inspect(engine).get_columns("master_profiles")}
    application_columns = {col["name"] for col in sa.inspect(engine).get_columns("applications")}
    assert "profile_type" in profile_columns
    assert "profile_id" in application_columns


def test_migration_backfills_profile_id_only_for_applications_with_generated_content(
    previous_head_db,
) -> None:
    alembic_cfg, engine = previous_head_db
    profile_id = _insert_master_profile_pre_migration(engine, email="max@example.com")
    job_offer_id = _insert_job_offer(engine)
    generated_1 = _insert_application(engine, job_offer_id, cover_letter_text="Sehr geehrte Damen...")
    generated_2 = _insert_application(engine, job_offer_id, cover_letter_text="Sehr geehrter Herr...")
    draft = _insert_application(engine, job_offer_id, cover_letter_text=None)

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        rows = {
            row.id: row.profile_id
            for row in conn.execute(sa.text("SELECT id, profile_id FROM applications"))
        }

    assert rows[generated_1] == profile_id
    assert rows[generated_2] == profile_id
    assert rows[draft] is None


def test_migration_leaves_profile_id_null_when_no_preexisting_profile(previous_head_db) -> None:
    alembic_cfg, engine = previous_head_db
    job_offer_id = _insert_job_offer(engine)
    application_id = _insert_application(engine, job_offer_id, cover_letter_text="Anschreiben-Text")

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT profile_id FROM applications WHERE id = :id"), {"id": application_id}
        ).fetchone()

    assert row.profile_id is None


def test_migration_downgrade_cleanly_reverses_both_column_additions(previous_head_db) -> None:
    alembic_cfg, engine = previous_head_db

    upgrade(alembic_cfg, "head")
    downgrade(alembic_cfg, "-1")

    profile_columns = {col["name"] for col in sa.inspect(engine).get_columns("master_profiles")}
    application_columns = {col["name"] for col in sa.inspect(engine).get_columns("applications")}
    assert "profile_type" not in profile_columns
    assert "profile_id" not in application_columns

    # `email` unique-ness is restored on downgrade.
    unique_constraints = sa.inspect(engine).get_unique_constraints("master_profiles")
    assert any(uc["column_names"] == ["email"] for uc in unique_constraints)


def test_migration_upgrade_head_twice_does_not_raise(previous_head_db) -> None:
    alembic_cfg, _engine = previous_head_db

    upgrade(alembic_cfg, "head")
    upgrade(alembic_cfg, "head")  # must be a no-op, not an error


@pytest.fixture
def orm_session():
    """In-memory SQLite via `Base.metadata.create_all()` (wie
    `tests/api/test_profile.py`) statt Alembic - für ORM-Ebene-Checks der
    neuen `master_profiles`-Constraints."""
    engine = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_two_profiles_with_same_email_but_different_profile_type_both_save(orm_session) -> None:
    orm_session.add(MasterProfile(full_name="IT Profil", email="same@example.com", profile_type="it"))
    orm_session.add(
        MasterProfile(full_name="Non-IT Profil", email="same@example.com", profile_type="full_life")
    )

    orm_session.commit()  # must not raise

    assert orm_session.query(MasterProfile).count() == 2


def test_second_profile_with_same_profile_type_is_rejected(orm_session) -> None:
    orm_session.add(MasterProfile(full_name="Erstes IT Profil", email="first@example.com", profile_type="it"))
    orm_session.commit()

    orm_session.add(MasterProfile(full_name="Zweites IT Profil", email="second@example.com", profile_type="it"))
    with pytest.raises(IntegrityError):
        orm_session.commit()


def test_second_profile_with_null_profile_type_still_saves(orm_session) -> None:
    orm_session.add(MasterProfile(full_name="Erstes IT Profil", email="first@example.com", profile_type="it"))
    orm_session.commit()

    orm_session.add(MasterProfile(full_name="Unassigned Profil", email="second@example.com", profile_type=None))

    orm_session.commit()  # must not raise: NULL never collides with NULL

    assert orm_session.query(MasterProfile).count() == 2
