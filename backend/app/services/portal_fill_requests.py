"""In-Memory-Registry für kurzlebige, einmalig verwendbare Fill-Requests
(KTD2, docs/plans/2026-09-22-003-feat-browser-extension-application-autofill-plan.md).

Die App legt beim Start eines Fills einen Request an (Schlüssel: Application
id), der die normalisierte LinkedIn-Job-URL auf den Request abbildet. Die
Erweiterung fragt mit ihrer aktuellen Seiten-URL den Kontext ab; ein
passender, nicht abgelaufener Request wird dabei EINMALIG konsumiert
(`consume_by_url`) und danach nie wieder ausgeliefert. Ein Backend-Neustart
verwirft alle offenen Requests - die Erweiterung erhält dann 404 und muss den
Fill erneut in der App starten.

Bewusst prozessweiter In-Memory-Zustand mit einem `threading.Lock` -
exakt dasselbe Muster wie `_active_sessions`/`_active_sessions_lock` in
`app.services.portal_agents.session` (U1) und
`_generating_job_offer_ids`/`_generating_lock` in `app.api.applications`.
Das setzt einen einzelnen uvicorn-Worker voraus (siehe
`assert_single_worker`, das beim App-Start laut fehlschlägt, wenn mehr als
ein Worker konfiguriert ist).
"""
from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

# Wie lange ein Fill-Request offen bleibt, bevor er als abgelaufen gilt.
# Großzügig genug für den Nutzer, den Tab zu öffnen und die Erweiterung
# laden zu lassen; klein genug, dass ein vergessener Request nicht dauerhaft
# als "offen" gilt (AE7).
FILL_REQUEST_TTL_SECONDS = 900

# Nur echte LinkedIn-Job-URLs werden normalisiert. Query und Fragment werden
# zuvor verworfen (KTD2: "strips query and fragment").
_LINKEDIN_JOB_PATH_RE = re.compile(r"^/jobs/view/(\d+)", re.IGNORECASE)

# Umgebungsvariablen, über die gängige ASGI-Server die Worker-Anzahl steuern.
_WORKER_ENV_VARS = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS")


@dataclass
class FillRequest:
    """Ein offener (oder bereits konsumierter) Fill-Request."""

    application_id: int
    job_url: str
    normalized_url: str
    created_at: datetime
    expires_at: datetime
    consumed: bool = False


_requests: dict[int, FillRequest] = {}
_requests_lock = threading.Lock()


def normalize_linkedin_job_url(url: str | None) -> str | None:
    """Normalisiert eine LinkedIn-Job-URL auf ihre kanonische Form
    `https://www.linkedin.com/jobs/view/{id}` (KTD2).

    Query und Fragment werden verworfen; Subdomains (z. B. `de.linkedin.com`)
    werden auf `www.` vereinheitlicht. Liefert `None`, wenn die URL keine
    erkennbare LinkedIn-Job-URL ist - z. B. eine externe Bewerbungsseite
    (R4-Fallback) oder eine LinkedIn-URL ohne `/jobs/view/{id}`.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None

    if parts.scheme not in ("http", "https"):
        return None

    host = (parts.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None

    match = _LINKEDIN_JOB_PATH_RE.match(parts.path)
    if match is None:
        return None

    return f"https://www.linkedin.com/jobs/view/{match.group(1)}"


def _purge_expired_locked(now: datetime) -> None:
    expired = [app_id for app_id, request in _requests.items() if request.expires_at <= now]
    for app_id in expired:
        del _requests[app_id]


def get_active(application_id: int) -> FillRequest | None:
    """Liefert den noch offenen (nicht konsumierten, nicht abgelaufenen)
    Request für `application_id` - Grundlage für die AE7-Deduplizierung."""
    now = datetime.now(timezone.utc)
    with _requests_lock:
        _purge_expired_locked(now)
        request = _requests.get(application_id)
        if request is None or request.consumed:
            return None
        return request


def create_or_get(
    application_id: int,
    job_url: str,
    normalized_url: str,
    ttl_seconds: float = FILL_REQUEST_TTL_SECONDS,
) -> FillRequest:
    """Legt einen Fill-Request an oder liefert den bestehenden offenen
    Request für dieselbe Application zurück (AE7: keine Duplikate)."""
    now = datetime.now(timezone.utc)
    with _requests_lock:
        _purge_expired_locked(now)
        existing = _requests.get(application_id)
        if existing is not None and not existing.consumed:
            return existing

        request = FillRequest(
            application_id=application_id,
            job_url=job_url,
            normalized_url=normalized_url,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        _requests[application_id] = request
        return request


def consume_by_url(url: str | None) -> FillRequest | None:
    """Konsumiert den ersten offenen Request, dessen normalisierte URL zu
    `url` passt - oder `None`, wenn nichts (mehr) passt (R14/AE3)."""
    normalized = normalize_linkedin_job_url(url)
    if normalized is None:
        return None

    now = datetime.now(timezone.utc)
    with _requests_lock:
        _purge_expired_locked(now)
        for request in _requests.values():
            if request.consumed or request.normalized_url != normalized:
                continue
            request.consumed = True
            return request
    return None


def clear() -> None:
    """Leert die Registry - ausschließlich für Tests."""
    with _requests_lock:
        _requests.clear()


class MultiWorkerConfigurationError(RuntimeError):
    """Mehr als ein Worker ist konfiguriert, während die Fill-Registry
    prozesslokal ist - Request-Matching würde stillschweigend brechen."""


def configured_worker_count() -> int:
    """Liest die konfigurierte Worker-Anzahl aus der Umgebung bzw. `sys.argv`.

    Gibt `1` zurück, wenn nichts gesetzt ist (der aktuelle Single-Worker-
    Default, siehe `backend/Dockerfile`)."""
    for var in _WORKER_ENV_VARS:
        raw = os.environ.get(var)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue

    argv = sys.argv
    for index, arg in enumerate(argv):
        if arg == "--workers" and index + 1 < len(argv):
            try:
                return int(argv[index + 1])
            except ValueError:
                pass
        elif arg.startswith("--workers="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                pass
    return 1


def assert_single_worker() -> None:
    """Bricht den App-Start laut ab, wenn mehr als ein Worker konfiguriert ist
    (KTD2). Wird aus `app.main.lifespan` aufgerufen."""
    count = configured_worker_count()
    if count > 1:
        raise MultiWorkerConfigurationError(
            "Die In-Memory-Fill-Registry (KTD2) setzt einen einzelnen uvicorn-"
            f"Worker voraus, aber es sind {count} Worker konfiguriert. Bitte "
            "mit einem Worker starten oder die Registry auf geteilten Zustand "
            "umstellen."
        )
