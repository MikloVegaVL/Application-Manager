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

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

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
