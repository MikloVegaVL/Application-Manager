"""Regression: `init_db()` routet korrekt zwischen `create_all()` (SQLite)
und `alembic upgrade head` (PostgreSQL), abhängig von `DATABASE_URL`.

Weder `test_migrations.py` (ruft Alembic direkt auf, nie über `init_db()`)
noch die API-Tests (die `init_db()` bewusst über eigene In-Memory-SQLite-
Fixtures umgehen, siehe `tests/api/test_applications.py`) rufen `init_db()`
selbst auf - der Routing-Zweig war dadurch ungetestet, obwohl er genau die
Funktion ist, deren fehlende Migrations-Anbindung den ursprünglichen Bug
verursachte (per Review aufgezeigt)."""
from unittest.mock import patch

from app.db import init_db as init_db_module


def test_init_db_uses_create_all_for_sqlite() -> None:
    with patch.object(init_db_module.settings, "DATABASE_URL", "sqlite:///./whatever.db"), \
        patch.object(init_db_module.Base.metadata, "create_all") as mock_create_all, \
        patch.object(init_db_module.command, "upgrade") as mock_upgrade:
        init_db_module.init_db()

    mock_create_all.assert_called_once_with(bind=init_db_module.engine)
    mock_upgrade.assert_not_called()


def test_init_db_uses_alembic_upgrade_head_for_postgres() -> None:
    with patch.object(
        init_db_module.settings, "DATABASE_URL", "postgresql://user:pass@db:5432/app"
    ), patch.object(init_db_module.Base.metadata, "create_all") as mock_create_all, patch.object(
        init_db_module.command, "upgrade"
    ) as mock_upgrade:
        init_db_module.init_db()

    mock_create_all.assert_not_called()
    mock_upgrade.assert_called_once()
    _alembic_cfg, revision = mock_upgrade.call_args.args
    assert revision == "head"
