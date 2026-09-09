"""Pydantic-Schemas des Application-Managers."""
from app.schemas.application import (
    ApplicationBase,
    ApplicationCreate,
    ApplicationGenerateRequest,
    ApplicationRead,
    ApplicationSendRequest,
    ApplicationUpdate,
)
from app.schemas.generation import AiGenerationResult
from app.schemas.health import HealthResponse
from app.schemas.job_offer import JobOfferBase, JobOfferCreate, JobOfferRead, JobOfferUpdate
from app.schemas.master_profile import (
    EducationEntry,
    ExperienceEntry,
    MasterProfileBase,
    MasterProfileCreate,
    MasterProfileRead,
    MasterProfileUpdate,
    ParsedCvProfile,
    ProfileAttachmentRead,
)

__all__ = [
    "AiGenerationResult",
    "ApplicationBase",
    "ApplicationCreate",
    "ApplicationGenerateRequest",
    "ApplicationRead",
    "ApplicationSendRequest",
    "ApplicationUpdate",
    "EducationEntry",
    "ExperienceEntry",
    "HealthResponse",
    "JobOfferBase",
    "JobOfferCreate",
    "JobOfferRead",
    "JobOfferUpdate",
    "MasterProfileBase",
    "MasterProfileCreate",
    "MasterProfileRead",
    "MasterProfileUpdate",
    "ParsedCvProfile",
    "ProfileAttachmentRead",
]
