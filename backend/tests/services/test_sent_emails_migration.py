"""Tests für die `sent_emails`-Migration (U1 des Plans:
docs/plans/2026-09-14-001-feat-application-email-log-plan.md).

Deckt ab: Tabellen-Erstellung, Backfill bereits vor diesem Feature
versendeter `Application`s (R10), Idempotenz bei erneutem `upgrade`, und
`downgrade()`.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.command import downgrade, upgrade
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI_PATH = _BACKEND_DIR / "alembic.ini"

# Letzter Head vor der neuen `sent_emails`-Migration - Tests bauen
# Alt-Zustand (bereits versendete Applications ohne Log-Tabelle) davor auf.
_PRE_MIGRATION_HEAD = "b3a9c1d2e4f5"


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
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT application_id, company, job_title, recipient_email, sent_at, "
                "sender_email, subject, attachment_filename FROM sent_emails "
                "ORDER BY application_id"
            )
        ).fetchall()


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


def test_upgrade_backfills_one_row_per_sent_application_only(migration_db) -> None:
    alembic_cfg, engine = migration_db
    sent_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)

    offer_a = _insert_job_offer(engine, source_url="https://a", company="Acme", title="Backend Dev")
    offer_b = _insert_job_offer(engine, source_url="https://b", company="Globex", title="Frontend Dev")
    _insert_application(
        engine, job_offer_id=offer_a, status="sent", sent_at=sent_at, sent_to_email="hr@acme.example"
    )
    _insert_application(
        engine, job_offer_id=offer_b, status="sent", sent_at=sent_at, sent_to_email="jobs@globex.example"
    )
    _insert_application(engine, job_offer_id=offer_a, status="draft", sent_at=None, sent_to_email=None)

    upgrade(alembic_cfg, "head")

    rows = _sent_email_rows(engine)
    assert len(rows) == 2
    assert {row.company for row in rows} == {"Acme", "Globex"}
    for row in rows:
        assert row.sender_email is None
        assert row.subject is None
        assert row.attachment_filename is None
        assert row.application_id is not None


def test_upgrade_with_no_sent_applications_backfills_nothing(migration_db) -> None:
    alembic_cfg, engine = migration_db
    offer = _insert_job_offer(engine, source_url="https://c", company="Initech", title="QA")
    _insert_application(engine, job_offer_id=offer, status="draft", sent_at=None, sent_to_email=None)

    upgrade(alembic_cfg, "head")

    assert _sent_email_rows(engine) == []


def test_rerunning_upgrade_does_not_duplicate_backfilled_rows(migration_db) -> None:
    alembic_cfg, engine = migration_db
    sent_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    offer = _insert_job_offer(engine, source_url="https://d", company="Umbrella", title="Sales")
    _insert_application(
        engine, job_offer_id=offer, status="sent", sent_at=sent_at, sent_to_email="hr@umbrella.example"
    )

    upgrade(alembic_cfg, "head")
    # Erneuter Lauf gegen dieselbe (bereits migrierte) DB, z. B. Teil eines
    # wiederholten Deploys - darf keinen zweiten Log-Eintrag anlegen.
    upgrade(alembic_cfg, "head")

    assert len(_sent_email_rows(engine)) == 1


def test_downgrade_drops_sent_emails_table(migration_db) -> None:
    alembic_cfg, engine = migration_db

    upgrade(alembic_cfg, "head")
    downgrade(alembic_cfg, _PRE_MIGRATION_HEAD)

    assert "sent_emails" not in sa.inspect(engine).get_table_names()
