"""ORM-Modell für zusätzliche Anhang-Dateien am Bewerber-Stammprofil.

Getrennt von `MasterProfile.cv_file_path`/`cv_filename` (der eine
Lebenslauf-Anhang-Datei): hier können bis zu `MAX_PROFILE_ATTACHMENTS`
(siehe `app.api.profile`) zusätzliche PDF-Dokumente (z. B. Zeugnisse,
Zertifikate) hinterlegt werden, die beim Versand einer Bewerbung als
zusätzliche E-Mail-Anhänge neben dem Lebenslauf verschickt werden (siehe
`app.api.applications.send_application`).
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.master_profile import MasterProfile


class ProfileAttachment(Base):
    """Eine einzelne zusätzliche Anhang-Datei (PDF) am Stammprofil."""

    __tablename__ = "profile_attachments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # `file_path` ist der Pfad auf der Festplatte, `filename` der
    # ursprüngliche Dateiname (für Content-Disposition/E-Mail-Anhang) -
    # gleiches Muster wie `MasterProfile.cv_file_path`/`cv_filename`.
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile: Mapped["MasterProfile"] = relationship("MasterProfile", back_populates="attachments")

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return f"<ProfileAttachment id={self.id} profile_id={self.profile_id} filename={self.filename!r}>"
