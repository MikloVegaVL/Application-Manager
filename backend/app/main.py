"""Einstiegspunkt der FastAPI-Anwendung."""
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.applications import router as applications_router
from app.api.cv_builder import router as cv_builder_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.portal_fill import router as portal_fill_router
from app.api.profile import router as profile_router
from app.api.sent_emails import router as sent_emails_router
from app.core.config import settings
from app.db.init_db import init_db
from app.services.portal_fill_requests import assert_single_worker

# `urllib3`/`requests` loggen vollständige Request-URLs auf DEBUG-Ebene, was
# credential-tragende URLs künftiger Job-Quellen preisgeben könnte -
# prozessweit unterdrücken.
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Legt beim App-Start alle Datenbank-Tabellen an (sofern nicht
    bereits vorhanden) und übergibt anschließend an die laufende App."""
    # KTD2: Die In-Memory-Fill-Registry setzt einen einzelnen uvicorn-Worker
    # voraus - mit mehreren Workern würde Request-Matching stillschweigend
    # brechen. Daher hier laut fehlschlagen, statt das zu riskieren.
    assert_single_worker()
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

# --- Trusted-Host: nur lokale Hostnamen (KTD13) ---
# Die API ist ein lokales Einzelnutzer-Werkzeug ohne Authentifizierung. Ohne
# diese Middleware würde ein DNS-Rebinding-Angriff (eine besuchte Seite, die
# auf `localhost` auflöst) die API direkt ansprechen können; erlaubt sind
# daher ausschließlich `localhost` und `127.0.0.1`.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

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
app.include_router(cv_builder_router, prefix=settings.API_V1_PREFIX)
app.include_router(sent_emails_router, prefix=settings.API_V1_PREFIX)
app.include_router(portal_fill_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
def read_root() -> dict[str, str]:
    """Einfacher Root-Endpoint zur Bestätigung, dass die API läuft."""
    return {"message": f"{settings.APP_NAME} API is running."}
