"""SQLAlchemy Datenbank-Setup: Engine, Session-Factory und Basisklasse.

Die Verbindung wird ausschließlich über die Umgebungsvariable
`DATABASE_URL` konfiguriert (gelesen via `app.core.config.settings`, das
auf `pydantic-settings` basiert und Prozess-Umgebungsvariablen automatisch
Vorrang vor Werten aus `.env` gibt). Dadurch passt sich die Anwendung ohne
Codeänderung an drei Szenarien an:

- **Lokale Entwicklung ohne Docker:** `DATABASE_URL` ist weder gesetzt noch
  in `.env` hinterlegt -> Fallback auf eine lokale SQLite-Datei
  (`sqlite:///./app.db`, siehe `Settings.DATABASE_URL`-Default).
- **Docker Compose:** `docker-compose.yml` setzt `DATABASE_URL` explizit auf
  eine PostgreSQL-Verbindung zum `db`-Service, z. B.
  `postgresql://user:password@db:5432/application_manager`.
- **Sonstige Produktivumgebung:** `DATABASE_URL` wird direkt als
  Umgebungsvariable des Deployments gesetzt.

In allen Fällen bleibt der restliche Code (Models, Schemas, Services)
unverändert - `create_engine()` unterscheidet lediglich anhand des
URL-Schemas, welche Connect-Optionen sinnvoll sind.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def is_sqlite_url(database_url: str) -> bool:
    """Erkennt eine SQLite-`DATABASE_URL` - öffentlich, damit andere Module
    (z. B. `app.db.init_db`, das je nach Datenbank zwischen `create_all()`
    und Alembic-Migrationen unterscheidet) dieselbe Prüfung nutzen können,
    statt sie ein zweites Mal zu implementieren."""
    return database_url.startswith("sqlite")


def escape_for_alembic_config(database_url: str) -> str:
    """Escaped `%` für die Übergabe an `alembic.config.Config.set_main_option()`.

    `Config.set_main_option()` schreibt den Wert in ein `configparser.ConfigParser`
    mit aktivierter `%`-Interpolation - ein Passwort mit einem wörtlichen `%`
    (z. B. URL-kodierte Sonderzeichen wie `%40` für `@`) lässt `set_main_option()`
    sofort mit `ValueError: invalid interpolation syntax` abstürzen, noch bevor
    eine Migration läuft (ce-debug-Untersuchung, 2026-08-20, per Review
    reproduziert). `%%` escaped korrekt und wird beim Auslesen über
    `get_main_option()` wieder zu `%` entfaltet - der Rückgabewert ist exakt
    die ursprüngliche URL. Genutzt von `app.db.init_db` und `alembic/env.py`."""
    return database_url.replace("%", "%%")


_is_sqlite = is_sqlite_url(settings.DATABASE_URL)

# SQLite erlaubt eine Connection standardmäßig nur im Thread, der sie
# geöffnet hat. FastAPI kann Requests jedoch aus unterschiedlichen Threads
# bedienen, weshalb dieses Flag ausschließlich für SQLite gesetzt wird.
connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    # Prüft Connections aus dem Pool vor Gebrauch mit einem leichten Ping.
    # Wichtig im Docker-Betrieb: verhindert "connection reset"-Fehler, wenn
    # der PostgreSQL-Container zwischenzeitlich neu gestartet wurde oder die
    # Verbindung durch Inaktivität verworfen wurde. Für SQLite wirkungslos,
    # aber unschädlich.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Gemeinsame Basisklasse, von der alle ORM-Modelle erben."""

    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI-Dependency: stellt pro Request eine DB-Session bereit und
    schließt sie garantiert wieder, auch im Fehlerfall."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
