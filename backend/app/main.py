"""Einstiegspunkt der FastAPI-Anwendung."""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.applications import router as applications_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.profile import router as profile_router
from app.core.config import settings
from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Legt beim App-Start alle Datenbank-Tabellen an (sofern nicht
    bereits vorhanden) und übergibt anschließend an die laufende App."""
    init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Backend-API für die persönliche Jobsuche- und "
        "Bewerbungsmanagement-Anwendung."
    ),
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(jobs_router, prefix=settings.API_V1_PREFIX)
app.include_router(profile_router, prefix=settings.API_V1_PREFIX)
app.include_router(applications_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
def read_root() -> dict[str, str]:
    """Einfacher Root-Endpoint zur Bestätigung, dass die API läuft."""
    return {"message": f"{settings.APP_NAME} API is running."}
