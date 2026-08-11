"""Datenbank-Initialisierung: legt beim App-Start alle Tabellen an.

Für die lokale Entwicklung mit SQLite genügt `Base.metadata.create_all()`.
Sobald produktiv gegen PostgreSQL gearbeitet wird, sollte stattdessen
Alembic für versionierte Migrationen genutzt werden (siehe `/backend/alembic`);
`init_db()` bleibt dafür trotzdem als Fallback für frische Dev-Datenbanken
nützlich, da `create_all()` bereits bestehende Tabellen nicht anfasst.
"""
import logging

# Der Import registriert alle Modelle in Base.metadata - ohne ihn wüsste
# create_all() nichts von JobOffer, MasterProfile und Application.
from app import models  # noqa: F401
from app.db.database import Base, engine

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Erstellt alle registrierten Tabellen, sofern sie noch nicht existieren."""
    logger.info("Initialisiere Datenbank-Tabellen ...")
    Base.metadata.create_all(bind=engine)
    logger.info("Datenbank-Tabellen erfolgreich angelegt/geprüft.")
