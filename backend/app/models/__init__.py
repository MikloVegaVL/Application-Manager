"""ORM-Modelle des Application-Managers.

Der explizite Import aller Modelle hier stellt sicher, dass sie in
`Base.metadata` registriert werden - Voraussetzung dafür, dass
`Base.metadata.create_all()` (siehe `app.db.init_db`) alle Tabellen anlegt
und Alembic später alle Modelle für Migrationen erkennt.
"""
from app.models.application import Application, ApplicationStatus
from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.models.profile_attachment import ProfileAttachment

__all__ = ["Application", "ApplicationStatus", "JobOffer", "MasterProfile", "ProfileAttachment"]
