"""ORM-Modell für eine konkrete Bewerbung zu einem Stellenangebot."""
import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.job_offer import JobOffer


class ApplicationStatus(str, enum.Enum):
    """Mögliche Bearbeitungsstände einer Bewerbung."""

    DRAFT = "draft"
    SENT = "sent"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    INTERVIEW = "interview"


class Application(Base):
    """Eine (ggf. KI-generierte) Bewerbung für ein bestimmtes Stellenangebot."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_offer_id: Mapped[int] = mapped_column(
        ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cover_letter_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # `native_enum=False` legt den Wert als VARCHAR ab statt als nativen
    # DB-Enum-Typ. Das hält den Wechsel SQLite -> PostgreSQL unkompliziert,
    # da für PostgreSQL sonst zusätzlich ein CREATE TYPE nötig wäre.
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=20, validate_strings=True),
        default=ApplicationStatus.DRAFT,
        nullable=False,
        index=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job_offer: Mapped["JobOffer"] = relationship(back_populates="applications")

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return f"<Application id={self.id} job_offer_id={self.job_offer_id} status={self.status}>"
