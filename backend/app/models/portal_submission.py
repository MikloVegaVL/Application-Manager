"""ORM-Modell für einen protokollierten Portal-Auto-Fill-Versand.

Jeder erfolgreiche Portal-Submit (siehe docs/plans/2026-09-19-002-feat-portal-
application-auto-fill-agent-plan.md, U7) erzeugt einen `PortalSubmission`-
Datensatz - exakt dasselbe Muster wie `SentEmail` (`app.models.sent_email`)
für den E-Mail-Versand.

`company`/`job_title`/`platform` werden zum Submit-Zeitpunkt aus dem
zugehörigen `JobOffer` übernommen (Snapshot) statt live über `job_offer`
verknüpft: wird die `Application` später gelöscht (`application_id` ->
`ondelete=SET NULL`), bleibt der Log-Eintrag trotzdem lesbar - das durable
Protokoll darf nicht durch eine spätere Löschung verschwinden.
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.application import Application


class PortalSubmission(Base):
    """Ein einzelner, tatsächlich erfolgter Portal-Auto-Fill-Submit."""

    __tablename__ = "portal_submissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Vom Client erzeugter Idempotenz-Schlüssel (KTD3): ein wiederholter
    # Report mit demselben `report_id` liefert die bestehende Zeile zurück,
    # statt eine zweite anzulegen. Nullable, da ältere Zeilen und nicht über
    # einen Report entstandene Einträge ihn nicht tragen. `unique=True,
    # index=True` erzeugt bewusst einen UNIQUE-Index (nicht eine
    # UNIQUE-Constraint) - der lässt sich in SQLite per `CREATE UNIQUE INDEX`
    # auf eine bestehende Tabelle legen (siehe Migration `d1a2b3c4e5f6`).
    report_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )

    # Snapshot statt Live-Join - bleibt auch nach Löschung der Application
    # lesbar (siehe Docstring oben).
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(100), nullable=True)

    portal_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `viewonly`: reines Lesen für den Link-through zur Application, kein
    # `back_populates` (gleiches Muster wie `SentEmail.application`).
    application: Mapped["Application | None"] = relationship(viewonly=True)

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return (
            f"<PortalSubmission id={self.id} application_id={self.application_id} "
            f"portal_url={self.portal_url!r}>"
        )
