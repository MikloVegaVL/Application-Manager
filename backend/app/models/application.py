"""ORM-Modell für eine konkrete Bewerbung zu einem Stellenangebot."""
import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
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
    # Empfängeradresse des tatsächlichen Mailversands - wird erst beim Versand
    # gesetzt (siehe `send_application`) und in der Bewerbungsübersicht
    # angezeigt, damit nachvollziehbar ist, wohin die Bewerbung ging.
    sent_to_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # Portal-Auto-Fill-Status (Playwright-gestützter Agent, siehe
    # docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md).
    # Bewusst kein `ApplicationStatus`-Wert (KTD3): `status` bildet das
    # finale, nutzersichtbare Ergebnis ab, dieser Automations-Zwischenstatus
    # ist unabhängig davon. Ein einfacher `String` statt `Enum(...,
    # native_enum=False)` wie bei `status` genügt hier, da die Werte
    # ausschließlich vom Python-Code der späteren Units (nicht von der DB)
    # geschrieben/geprüft werden.
    automation_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Doppelfunktion je nach `automation_state` (KTD3): bei "paused" der
    # Pausengrund (captcha/low_confidence_field/pre_submit_confirmation), bei
    # "failed" der Fehlgrund (timeout/iframe_not_found/unhandled_error/
    # cancelled_by_user). Wird von U1 selbst nicht beschrieben.
    action_needed_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Konkretes Feld/Frage-Label zur Pause (R9/KTD1) - ergänzt
    # `action_needed_reason` um das "wo". Wird bei jedem Zustandsübergang ohne
    # Detail auf `None` zurückgesetzt.
    action_needed_detail: Mapped[str | None] = mapped_column(String(80), nullable=True)
    automation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job_offer: Mapped["JobOffer"] = relationship(back_populates="applications")

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return f"<Application id={self.id} job_offer_id={self.job_offer_id} status={self.status}>"
