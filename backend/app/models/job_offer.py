"""ORM-Modell für gescrapte Stellenangebote."""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.application import Application


class JobOffer(Base):
    """Ein von einer Quelle (z. B. Arbeitsagentur-API, Scraping) importiertes
    Stellenangebot."""

    __tablename__ = "job_offers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    applications: Mapped[list["Application"]] = relationship(
        back_populates="job_offer",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return f"<JobOffer id={self.id} title={self.title!r} company={self.company!r}>"
