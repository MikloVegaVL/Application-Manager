"""API-Router für den Portal-Auto-Fill-Agenten (U6): Start/Status/Continue/
Cancel eines Personio-Auto-Fill-Laufs.

Bleibt bewusst dünn (siehe Auftrag/Plan): der eigentliche Fill-/Submit-Ablauf
läuft komplett im Session-Hintergrund-Thread (`app.services.portal_agents.
session`/`personio`), NICHT hier - diese Endpunkte fassen `session.page`
NIE an, sondern nur Flags/Events (`resume()`/`request_cancel()`) bzw. lesen
den `Application`-DB-Zustand, der die alleinige Quelle der Wahrheit für den
Automations-Status ist (dasselbe Muster wie in `session.py`).

`POST .../start` baut die konkrete `PersonioField`-Liste aus den echten
Profildaten (R3/R4) - WELCHE Werte gefüllt werden, ist hier verdrahtet, WIE
sie gefüllt werden, bleibt vollständig U3/U4 (`base.py`/`personio.py`)
überlassen.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.application import Application
from app.models.master_profile import MasterProfile
from app.schemas.application import ApplicationRead
from app.schemas.portal_fill import PortalFillStartRequest, PortalFillStatusResponse
from app.services.portal_agents import personio as personio_module
from app.services.portal_agents import session as session_module
from app.services.portal_agents.outcome import RunState, failure_class_for
from app.services.portal_agents.personio import PersonioField
from app.services.portal_agents.session import SessionAlreadyActiveError

router = APIRouter(prefix="/applications", tags=["Portal Auto-Fill"])


def _build_personio_fields(profile: MasterProfile) -> list[PersonioField]:
    """Baut die Standard-`PersonioField`-Liste aus den echten Profildaten
    (R3/R4) - jedes Feld nur, wenn der zugrunde liegende Profilwert gesetzt
    ist (R12-Vorbedingung: U3 muss nur Felder mit tatsächlichem Wert
    versuchen). Label-/Autocomplete-Ratespiel ist bewusst best-effort (siehe
    U3s accessible-first-Suche in `locate_field()`): ein nicht treffendes
    Label führt zu einem UNMAPPED-Feld und damit einer sichtbaren
    "Action needed"-Pause statt eines stillen Fehlers.
    """
    fields: list[PersonioField] = []

    if profile.full_name:
        fields.append(PersonioField(kind="text", value=profile.full_name, label="Name", autocomplete="name"))
    if profile.email:
        fields.append(
            PersonioField(
                kind="text", value=profile.email, label="Email", autocomplete="email", input_type="email"
            )
        )
    if profile.phone:
        fields.append(
            PersonioField(
                kind="text", value=profile.phone, label="Phone", autocomplete="tel", input_type="tel"
            )
        )
    if profile.address:
        fields.append(
            PersonioField(kind="text", value=profile.address, label="Address", autocomplete="street-address")
        )
    if profile.linkedin:
        fields.append(PersonioField(kind="text", value=profile.linkedin, label="LinkedIn"))
    if profile.website:
        fields.append(PersonioField(kind="text", value=profile.website, label="Website"))

    if profile.cv_file_path:
        # `upload_attachment_file()` (U3) ist duck-typed - sie braucht nur
        # `.file_path`/`.filename`, keinen echten `ProfileAttachment` (siehe
        # Auftrag/Moduldoc von `base.py`).
        cv_attachment = SimpleNamespace(file_path=profile.cv_file_path, filename=profile.cv_filename)
        fields.append(PersonioField(kind="file", value=cv_attachment, label="Resume"))

    for attachment in profile.attachments:
        # Ohne Kenntnis des tatsächlichen Feld-Labels im jeweiligen Personio-
        # Formular ist der Dateiname der einzig verfügbare Anhaltspunkt - trifft
        # er nicht, landet das Feld korrekt als UNMAPPED (R12), statt in den
        # (ggf. bereits durch den Lebenslauf belegten) ersten Datei-Input zu
        # geraten.
        fields.append(PersonioField(kind="file", value=attachment, label=attachment.filename))

    return fields


def _get_active_session(application_id: int) -> session_module.PortalFillSession | None:
    """Liest die In-Memory-Session-Registry aus `session.py` - kein eigenes
    öffentliches Accessor-API existiert dafür (siehe U2), daher direkter
    Zugriff auf `_active_sessions`/`_active_sessions_lock`, exakt wie
    `personio.py` bereits auf `session_module._StopRun`/`_unregister`
    zugreift (etabliertes Muster innerhalb dieses Pakets)."""
    with session_module._active_sessions_lock:
        return session_module._active_sessions.get(application_id)


@router.post("/{application_id}/portal-fill/start", response_model=ApplicationRead)
def start_portal_fill(
    application_id: int, payload: PortalFillStartRequest, db: Session = Depends(get_db)
) -> Application:
    """Startet einen Personio-Auto-Fill-Lauf für `application_id` in einem
    headless Browser (R1/R2). Lehnt eine Nicht-`https://`-URL sofort ab -
    bevor überhaupt ein Browser geöffnet wird (KTD11)."""
    if not payload.application_form_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Die Formular-URL muss mit https:// beginnen.",
        )

    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Es wurde noch kein Profil angelegt. Bitte zunächst über PUT /api/profile anlegen.",
        )

    fields = _build_personio_fields(profile)
    run_fn = personio_module.build_personio_run_fn(fields, dry_run=payload.dry_run)

    try:
        session_module.start_session(application_id, payload.application_form_url, run_fn)
    except SessionAlreadyActiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - Browser-Start-Fehler (KTD10), z. B. fehlendes Display
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    # `start_session()` kehrt erst zurück, NACHDEM `automation_state=
    # "running"` durch den Hintergrund-Thread committed wurde (siehe
    # `session.py`) - über eine ANDERE `SessionLocal()`-Session als `db`
    # hier. `db`s Identity-Map hält noch den alten Stand von `application`
    # (vor dem Start) - `refresh()` holt den frisch committeten Wert.
    db.refresh(application)
    return application


@router.get("/{application_id}/portal-fill/status", response_model=PortalFillStatusResponse)
def get_portal_fill_status(application_id: int, db: Session = Depends(get_db)) -> PortalFillStatusResponse:
    """Liefert den aktuellen Automations-Status direkt aus der `Application`-
    Zeile - funktioniert unabhängig davon, ob gerade ein Registry-Eintrag
    existiert (die DB-Zeile ist laut U2-Design die alleinige Quelle der
    Wahrheit für den Status, den U7 pollt)."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    # KTD1/KTD5: `failure_class` NUR für einen echten Fehlerlauf ableiten -
    # ein Pausen-Grund (z. B. "captcha") darf nie als terminaler Fehler
    # gelesen werden.
    failure_class = None
    if application.automation_state == RunState.FAILED.value:
        failure_class = failure_class_for(application.action_needed_reason).value

    return PortalFillStatusResponse(
        automation_state=application.automation_state,
        action_needed_reason=application.action_needed_reason,
        action_needed_detail=application.action_needed_detail,
        failure_class=failure_class,
    )


@router.post("/{application_id}/portal-fill/continue", response_model=ApplicationRead)
def continue_portal_fill(application_id: int, db: Session = Depends(get_db)) -> Application:
    """Setzt nur das Resume-Event (R10/R11) - fasst NIE `session.page` an
    (siehe Moduldoc). 404, wenn für diese `application_id` keine Sitzung in
    der Registry aktiv ist."""
    session = _get_active_session(application_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Für diese Bewerbung läuft aktuell kein Portal-Auto-Fill-Lauf.",
        )
    session.resume()

    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")
    return application


@router.post("/{application_id}/portal-fill/cancel", response_model=ApplicationRead)
def cancel_portal_fill(application_id: int, db: Session = Depends(get_db)) -> Application:
    """Setzt das Abbruch-Flag (R10) - der besitzende Session-Thread schließt
    den Browser selbst beim nächsten Checkpoint (siehe `session.py`). 404,
    wenn für diese `application_id` keine Sitzung in der Registry aktiv ist.

    P1-Fix (mehrere Reviewer): zusätzlich zu `request_cancel()` wird auch
    `resume()` aufgerufen - genau wie `shutdown_all_sessions()` in
    `session.py` es bereits vormacht. Ohne das bliebe eine PAUSIERTE Sitzung
    in `pause()`s `wait()` hängen (`cancel_requested` wird dort erst NACH dem
    Aufwachen geprüft) und der Abbruch würde erst nach bis zu
    `PAUSE_TIMEOUT_SECONDS` (aktuell 1h) wirksam."""
    session = _get_active_session(application_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Für diese Bewerbung läuft aktuell kein Portal-Auto-Fill-Lauf.",
        )
    session.request_cancel()
    session.resume()

    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")
    return application
