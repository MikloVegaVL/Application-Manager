"""Einstiegspunkt der FastAPI-Anwendung."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Backend-API für die persönliche Jobsuche- und "
        "Bewerbungsmanagement-Anwendung."
    ),
    version="0.1.0",
)

# --- CORS-Konfiguration: erlaubt Zugriffe vom Angular-Dev-Server ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Router-Registrierung ---
app.include_router(health_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
def read_root() -> dict[str, str]:
    """Einfacher Root-Endpoint zur Bestätigung, dass die API läuft."""
    return {"message": f"{settings.APP_NAME} API is running."}
