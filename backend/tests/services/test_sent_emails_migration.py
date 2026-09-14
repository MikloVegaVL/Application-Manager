"""Tests für die `sent_emails`-Migration (U1 des Plans:
docs/plans/2026-09-14-001-feat-application-email-log-plan.md).

Deckt ab: Tabellen-Erstellung, Backfill bereits vor diesem Feature
versendeter `Application`s (R10) - unabhängig vom *aktuellen* Status
(Review-Fund) und defensiv gegen fehlende `sent_to_email` (Review-Fund) -,
Idempotenz des Backfills selbst (nicht nur von `alembic upgrade head`,
das bei bereits erreichtem Head trivial nichts tut), und `downgrade()`.
"""
from __future__ import annotations

import importlib.util
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.command import downgrade, upgrade
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI_PATH = _BACKEND_DIR / "alembic.ini"
_MIGRATION_PATH = _BACKEND_DIR / "alembic" / "versions" / "40770d5086f1_add_sent_emails_table.py"

# Letzter Head vor der neuen `sent_emails`-Migration - Tests bauen
# Alt-Zustand (bereits versendete Applications ohne Log-Tabelle) davor auf.
_PRE_MIGRATION_HEAD = "b3a9c1d2e4f5"


def _load_migration_module() -> ModuleType:
    """Lädt die Migrationsdatei direkt per Pfad (kein Package, da
    `alembic/versions/` kein `__init__.py` hat und der Dateiname mit einer
    Ziffer beginnt) - so kann `_backfill_already_sent_applications` isoliert
    von `alembic upgrade head` erneut aufgerufen werden. `upgrade(cfg,
    "head")` ein zweites Mal ist dafür ungeeignet: bei bereits erreichtem
    Head lässt Alembic die `upgrade()`-Funktion der Revision komplett aus
    (keine erneute DDL/Backfill-Ausführung), das würde den `already_logged`-
    Guard nie wirklich prüfen (Review-Fund)."""
    spec = importlib.util.spec_from_file_location("sent_emails_migration_module", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration_db():
    """Frische SQLite-Datei, hochgezogen bis exakt vor die `sent_emails`-
    Migration, damit Test-Applications im Alt-Zustand eingefügt werden
    können, bevor deren `upgrade()` (inkl. Backfill) läuft."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "migration-check.db"
        database_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, _PRE_MIGRATION_HEAD)

        engine = sa.create_engine(database_url)
        try:
            yield alembic_cfg, engine
        finally:
            engine.dispose()


def _insert_job_offer(engine: sa.Engine, *, source_url: str, company: str, title: str) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "INSERT INTO job_offers (title, company, source_url, source_platform, "
                "is_processed) VALUES (:title, :company, :source_url, 'test', 0)"
            ),
            {"title": title, "company": company, "source_url": source_url},
        )
        return result.lastrowid


def _insert_application(
    engine: sa.Engine,
    *,
    job_offer_id: int,
    status: str = "sent",
    sent_at: datetime | None = None,
    sent_to_email: str | None = None,
) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "INSERT INTO applications (job_offer_id, status, sent_at, sent_to_email) "
                "VALUES (:job_offer_id, :status, :sent_at, :sent_to_email)"
            ),
            {
                "job_offer_id": job_offer_id,
                "status": status,
                "sent_at": sent_at,
                "sent_to_email": sent_to_email,
            },
        )
        return result.lastrowid


def _sent_email_rows(engine: sa.Engine) -> list[sa.Row]:
    # Reflektierte `Table` statt `sa.text(...)`: liefert `sent_at` als
    # typisiertes `datetime`-Objekt zurück statt als rohen SQLite-String, was
    # Wertvergleiche in Tests fragil machen würde.
    metadata = sa.MetaData()
    sent_emails = sa.Table("sent_emails", metadata, autoload_with=engine)
    with engine.connect() as conn:
        return conn.execute(sa.select(sent_emails).order_by(sent_emails.c.application_id)).fetchall()


def test_upgrade_creates_sent_emails_table_with_expected_columns(migration_db) -> None:
    alembic_cfg, engine = migration_db

    upgrade(alembic_cfg, "head")

    columns = {col["name"] for col in sa.inspect(engine).get_columns("sent_emails")}
    assert columns == {
        "id",
        "application_id",
        "company",
        "job_title",
        "recipient_email",
        "sent_at",
        "sender_email",
        "subject",
        "attachment_filename",
        "created_at",
    }


def test_upgrade_backfills_one_row_per_sent_application_with_correct_field_values(migration_db) -> None:
    alembic_cfg, engine = migration_db
    sent_at_a = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    sent_at_b = datetime(2026, 9, 2, 11, 30, tzinfo=timezone.utc)

    offer_a = _insert_job_offer(engine, source_url="https://a", company="Acme", title="Backend Dev")
    offer_b = _insert_job_offer(engine, source_url="https://b", company="Globex", title="Frontend Dev")
    _insert_application(
        engine, job_offer_id=offer_a, status="sent", sent_at=sent_at_a, sent_to_email="hr@acme.example"
    )
    _insert_application(
        engine, job_offer_id=offer_b, status="sent", sent_at=sent_at_b, sent_to_email="jobs@globex.example"
    )
    _insert_application(engine, job_offer_id=offer_a, status="draft", sent_at=None, sent_to_email=None)

    upgrade(alembic_cfg, "head")

    rows = {row.recipient_email: row for row in _sent_email_rows(engine)}
    assert set(rows) == {"hr@acme.example", "jobs@globex.example"}

    acme_row = rows["hr@acme.example"]
    assert acme_row.company == "Acme"
    assert acme_row.job_title == "Backend Dev"
    assert acme_row.sent_at.replace(tzinfo=timezone.utc) == sent_at_a
    assert acme_row.sender_email is None
    assert acme_row.subject is None
    assert acme_row.attachment_filename is None
    assert acme_row.application_id is not None

    globex_row = rows["jobs@globex.example"]
    assert globex_row.company == "Globex"
    assert globex_row.job_title == "Frontend Dev"


def test_upgrade_backfills_an_application_whose_status_later_advanced_past_sent(migration_db) -> None:
    """Covers the review finding: `PUT /applications/{id}` lets status move
    on to accepted/rejected/interview without clearing sent_at/sent_to_email
    - the backfill must still find these, not just status='sent' rows."""
    alembic_cfg, engine = migration_db
    sent_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    offer = _insert_job_offer(engine, source_url="https://e", company="Initrode", title="DevOps")
    _insert_application(
        engine, job_offer_id=offer, status="accepted", sent_at=sent_at, sent_to_email="hr@initrode.example"
    )

    upgrade(alembic_cfg, "head")

    rows = _sent_email_rows(engine)
    assert len(rows) == 1
    assert rows[0].recipient_email == "hr@initrode.example"


def test_upgrade_skips_a_row_with_sent_at_but_no_recipient_email(migration_db) -> None:
    """Covers the review finding: a row with sent_at set but sent_to_email
    still NULL (reachable via PUT, which never validates the two together)
    must be skipped, not crash the whole migration on the NOT NULL
    constraint."""
    alembic_cfg, engine = migration_db
    sent_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    offer = _insert_job_offer(engine, source_url="https://f", company="Soylent", title="PM")
    _insert_application(engine, job_offer_id=offer, status="sent", sent_at=sent_at, sent_to_email=None)

    upgrade(alembic_cfg, "head")

    assert _sent_email_rows(engine) == []


def test_upgrade_with_no_sent_applications_backfills_nothing(migration_db) -> None:
    alembic_cfg, engine = migration_db
    offer = _insert_job_offer(engine, source_url="https://c", company="Initech", title="QA")
    _insert_application(engine, job_offer_id=offer, status="draft", sent_at=None, sent_to_email=None)

    upgrade(alembic_cfg, "head")

    assert _sent_email_rows(engine) == []


def test_rerunning_backfill_directly_does_not_duplicate_rows(migration_db) -> None:
    alembic_cfg, engine = migration_db
    sent_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    offer = _insert_job_offer(engine, source_url="https://d", company="Umbrella", title="Sales")
    _insert_application(
        engine, job_offer_id=offer, status="sent", sent_at=sent_at, sent_to_email="hr@umbrella.example"
    )

    upgrade(alembic_cfg, "head")
    # Ruft den Backfill isoliert ein zweites Mal auf (siehe `_load_migration_
    # module`-Docstring, warum ein zweites `upgrade(cfg, "head")` dafür
    # ungeeignet ist) - simuliert z. B. einen erneuten Deploy-Lauf, der
    # denselben Code nochmal ausführt.
    module = _load_migration_module()
    with engine.begin() as conn:
        module._backfill_already_sent_applications(conn)

    assert len(_sent_email_rows(engine)) == 1


def test_downgrade_drops_sent_emails_table(migration_db) -> None:
    alembic_cfg, engine = migration_db

    upgrade(alembic_cfg, "head")
    downgrade(alembic_cfg, _PRE_MIGRATION_HEAD)

    assert "sent_emails" not in sa.inspect(engine).get_table_names()
