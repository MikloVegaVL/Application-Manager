"""ORM-Modell für einen protokollierten Bewerbungsmail-Versand.

Jeder erfolgreiche Versand über `send_application_email` erzeugt einen
eigenen `SentEmail`-Datensatz (siehe `app.api.applications`), statt wie
zuvor nur `Application.sent_at`/`sent_to_email` zu überschreiben. So bleibt
die Historie über mehrfache Versände (z. B. nach erneutem Senden) erhalten.

`company`/`job_title` werden zum Versandzeitpunkt aus dem zugehörigen
`JobOffer` übernommen (Snapshot) statt live über `job_offer` verknüpft: wird
die `Application` später gelöscht (`application_id` -> `ondelete=SET NULL`),
bleibt der Log-Eintrag trotzdem lesbar - das durable Protokoll darf nicht
durch eine spätere Löschung verschwinden.
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.application import ApplicationStatus

if TYPE_CHECKING:
    from app.models.application import Application


class SentEmail(Base):
    """Ein einzelner, tatsächlich erfolgter Bewerbungsmail-Versand."""

    __tablename__ = "sent_emails"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Snapshot statt Live-Join - bleibt auch nach Löschung der Application
    # lesbar (siehe Docstring oben).
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)

    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Nullable: bei Altbestand-Backfill (bereits vor diesem Feature
    # versendete Bewerbungen) unbekannt, da nie erfasst.
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Alle tatsächlich mitgeschickten Dateinamen in Versandreihenfolge
    # (Lebenslauf zuerst, danach die zusätzlichen Profil-Anhänge) - als Liste
    # statt eines einzelnen Feldes, damit das Protokoll zeigt, was wirklich
    # angehängt wurde, nicht nur den Lebenslauf. JSON wie die strukturierten
    # Listen in `MasterProfile` (identisch unter SQLite und PostgreSQL).
    # Leer, wenn für Altbestand nie erfasst (Backfill).
    attachment_filenames: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `viewonly`: reines Lesen für den Link-through zur Application (R5) -
    # kein `back_populates` auf `Application`, da diese Beziehung dort nicht
    # gebraucht wird. Eager-geladen per `joinedload` in `app.api.sent_emails`,
    # damit `job_offer_id` unten ohne N+1-Query pro Zeile auskommt.
    application: Mapped["Application | None"] = relationship(viewonly=True)

    @property
    def job_offer_id(self) -> int | None:
        """Für den Link-through zum Editor (`/editor/:jobOfferId`, R5) - kein
        Snapshot wie `company`/`job_title`: wird `None`, sobald die
        Application (und damit die Verlinkung) nicht mehr existiert, statt
        auf eine dann ohnehin nicht mehr erreichbare Seite zu verweisen."""
        return self.application.job_offer_id if self.application is not None else None

    @property
    def ad_url(self) -> str | None:
        """Live-Link zur ursprünglichen Stellenanzeige (`JobOffer.source_url`)
        - wie `job_offer_id` kein Snapshot, wird `None` sobald die Application
        gelöscht ist."""
        return self.application.job_offer.source_url if self.application is not None else None

    @property
    def outcome(self) -> str:
        """Live-Entscheidungsstatus der verknüpften Application ("offer" /
        "rejection" / "pending") - kein Snapshot vom Versandzeitpunkt (R3):
        ein erneuter Versand zeigt auf jeder Log-Zeile den aktuellen Ausgang,
        und der Ausgang kann sich nach dem Versand noch ändern. "pending" bei
        fehlender Entscheidung (draft/sent/interview) oder wenn die
        Application seither gelöscht wurde (R4). Bewusst ein einfacher str
        statt eines geteilten Enums (KTD1) - keine Kopplung an den
        unabhängigen "Run outcome"-Begriff aus dem Portal-Auto-Fill."""
        if self.application is None:
            return "pending"
        if self.application.status == ApplicationStatus.ACCEPTED:
            return "offer"
        if self.application.status == ApplicationStatus.REJECTED:
            return "rejection"
        return "pending"

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return (
            f"<SentEmail id={self.id} application_id={self.application_id} "
            f"recipient_email={self.recipient_email!r}>"
        )
