"""ORM-Modell für das persönliche Bewerber-Stammprofil.

Da die Anwendung für den persönlichen Gebrauch konzipiert ist, existiert in
der Regel genau ein `MasterProfile`-Datensatz. Er dient als Quelle für das
automatisierte Zuschneiden ("Tailoring") von Anschreiben und Lebenslauf auf
ein konkretes Stellenangebot.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.profile_attachment import ProfileAttachment


class MasterProfile(Base):
    """Stammdaten, Werdegang und Skills des Bewerbers."""

    __tablename__ = "master_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Strukturierte Listen (z. B. Stationen im Werdegang, Ausbildungen,
    # Skills) werden als JSON abgelegt. Der JSON-Typ von SQLAlchemy
    # funktioniert identisch unter SQLite (TEXT-Serialisierung) und
    # PostgreSQL (natives JSONB-kompatibles Verhalten).
    experiences_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    education_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    skills_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Vom Nutzer hochgeladene Lebenslauf-Datei (unverändert, kein KI-Rendering
    # mehr) - wird beim Versand einer Bewerbung als E-Mail-Anhang verwendet
    # (siehe `app.api.profile`, `app.api.applications.send_application`).
    # `cv_file_path` ist der Pfad auf der Festplatte, `cv_filename` der
    # ursprüngliche Dateiname (für Content-Disposition/E-Mail-Anhang).
    cv_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cv_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Bis zu drei zusätzliche PDF-Anhänge (z. B. Zeugnisse, Zertifikate),
    # die beim Versand einer Bewerbung neben dem Lebenslauf mitgeschickt
    # werden (siehe `ProfileAttachment`, `app.api.profile`,
    # `app.api.applications.send_application`). `order_by` hält die
    # Reihenfolge stabil (Upload-Reihenfolge) unabhängig von DB-internem
    # Zeilen-Ordering.
    attachments: Mapped[list["ProfileAttachment"]] = relationship(
        "ProfileAttachment",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="ProfileAttachment.created_at",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return f"<MasterProfile id={self.id} full_name={self.full_name!r}>"
