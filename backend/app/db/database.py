"""SQLAlchemy Datenbank-Setup: Engine, Session-Factory und Basisklasse.

Die Verbindung wird ausschließlich über `DATABASE_URL` (siehe
`app.core.config.settings`) konfiguriert. Für die lokale Entwicklung zeigt
sie standardmäßig auf eine SQLite-Datei; für den Produktivbetrieb genügt es,
`DATABASE_URL` in der `.env` auf eine PostgreSQL-Verbindung umzustellen
(z. B. `postgresql://user:password@host:5432/dbname`) - der restliche
Code (Models, Schemas, Services) bleibt unverändert.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# SQLite erlaubt eine Connection standardmäßig nur im Thread, der sie
# geöffnet hat. FastAPI kann Requests jedoch aus unterschiedlichen Threads
# bedienen, weshalb dieses Flag ausschließlich für SQLite gesetzt wird.
# PostgreSQL benötigt dieses Connect-Arg nicht.
connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

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
