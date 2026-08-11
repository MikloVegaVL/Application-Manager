"""Healthcheck-Endpoint zur Überwachung der API-Verfügbarkeit."""
from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Gibt den aktuellen Betriebsstatus der API zurück."""
    return HealthResponse(status="ok")
