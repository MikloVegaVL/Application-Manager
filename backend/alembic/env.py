"""Alembic-Umgebung: verbindet Migrationen mit der bestehenden SQLAlchemy-
Konfiguration statt einer eigenen, duplizierten Verbindungs-URL in
alembic.ini.

`DATABASE_URL` kommt bewusst aus `app.core.config.settings` (nicht aus einer
fest hinterlegten `sqlalchemy.url` in alembic.ini) - dieselbe Quelle, die
auch `app.db.database.engine` verwendet (siehe deren Docstring zu
Dev/Docker/Produktiv-Szenarien). So gilt für Migrationen immer dieselbe
Verbindung wie für die laufende App, ohne Zugangsdaten zweifach zu pflegen.

`target_metadata = Base.metadata` (nach Import von `app.models`, das alle
Modelle registriert - siehe `app/models/__init__.py`) ermöglicht
`alembic revision --autogenerate`, künftige Modelländerungen automatisch als
Migration vorzuschlagen.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401 - registriert alle Modelle in Base.metadata
from app.core.config import settings
from app.db.database import Base, escape_for_alembic_config, is_sqlite_url

config = context.config

# Nur auf `settings.DATABASE_URL` zurückfallen, wenn noch keine URL gesetzt
# ist - ein Aufrufer, der `Config.set_main_option("sqlalchemy.url", ...)`
# selbst schon gesetzt hat (z. B. Tests gegen eine Wegwerf-SQLite-Datei),
# soll das nicht überschrieben bekommen.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", escape_for_alembic_config(settings.DATABASE_URL))

if config.config_file_name is not None:
    # `disable_existing_loggers=False`: `fileConfig()` deaktiviert sonst
    # (Default `disable_existing_loggers=True`) jeden bereits registrierten
    # Logger, der nicht in alembic.ini gelistet ist - da `init_db()` diese
    # Migration in-process beim App-Start ausführt (nicht als separater
    # CLI-Prozess), würde das jeden App-Logger dauerhaft verstummen lassen,
    # der vor `lifespan()` bereits importiert wurde (per Review reproduziert
    # und mehrfach unabhängig bestätigt).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Erzeugt SQL-Skripte ohne aktive DB-Verbindung (`alembic upgrade --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Führt Migrationen über eine echte DB-Verbindung aus - der Normalfall
    (siehe `app.db.init_db.init_db()`, das dies beim App-Start aufruft)."""
    url = config.get_main_option("sqlalchemy.url", "")
    # `init_db()` läuft in FastAPIs `lifespan()` VOR `yield` - der ASGI-Server
    # nimmt also noch keine Requests an, ein Readiness-Probe hätte also nichts,
    # worauf er reagieren könnte. Ohne Timeout kann eine unerreichbare DB oder
    # ein von einer anderen Instanz gehaltener DDL-Lock den App-Start
    # unbegrenzt blockieren statt schnell und laut zu scheitern (per Review
    # aufgezeigt). SQLite (Tests, lokale Dev-DB) kennt weder `connect_timeout`
    # noch psycopg2s `-c`-Optionen, daher nur für PostgreSQL gesetzt.
    connect_args = (
        {}
        if is_sqlite_url(url)
        else {"connect_timeout": 10, "options": "-c lock_timeout=30s -c statement_timeout=30s"}
    )
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
