"""Pydantic-Schemas für den Healthcheck-Endpoint."""
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Antwortmodell des `/api/health`-Endpoints."""

    status: str
