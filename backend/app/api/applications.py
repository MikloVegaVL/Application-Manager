"""API-Router für Bewerbungen: KI-Generierung (Anschreiben) und Mailversand.

Der Lebenslauf wird nicht mehr serverseitig generiert/gerendert - der
Mailversand hängt die vom Nutzer im Profil hochgeladene Lebenslauf-Datei an
(siehe `app.api.profile`, `MasterProfile.cv_file_path`)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.models.application import Application, ApplicationStatus
from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.models.sent_email import SentEmail
from app.schemas.application import (
    ApplicationGenerateRequest,
    ApplicationRead,
    ApplicationSendRequest,
    ApplicationUpdate,
)
from app.services.ai_generator import ApplicationGenerationError, generate_application_content
from app.services.mail_service import MailSendError, send_application_email

router = APIRouter(prefix="/applications", tags=["Applications"])

# Verhindert überlappende KI-Generierungen für dasselbe Stellenangebot
# (ce-debug-Untersuchung, 2026-08-28): `ApplicationEditorComponent` stößt bei
# jedem Mounten mit noch leerem `cover_letter_text` erneut eine Generierung
# an - ohne diese Sperre feuert jeder erneute Besuch des Editors für denselben
# Job (Browser-Zurück, Reload, erneuter Klick auf "Bewerbung generieren")
# einen weiteren vollständigen, mehrminütigen KI-Lauf, der hinter
# `llm_client._ollama_lock` seriell wartet und das Ergebnis des vorherigen
# Laufs überschreibt, sobald er fertig ist. Für den Nutzer wirkte das wie ein
# Editor, der endlos ohne Ergebnis läuft - live am laufenden Stack bestätigt
# (Ollama blieb nach einer bereits abgeschlossenen Generierung weiter mit
# >2000% CPU beschäftigt, ohne dass ein neuer Request geloggt wurde).
#
# Nur prozessweit wirksam (In-Memory-`set`, kein DB-/Redis-Zustand) - passt
# zum aktuellen Deployment (`uvicorn app.main:app` ohne `--workers`, siehe
# backend/Dockerfile, also ein einzelner Prozess). Würde das Backend je mit
# mehreren Workern/Replikas betrieben, hätte jeder Prozess seine eigene Sperre
# und überlappende Generierungen wären wieder möglich, ohne dass das hier
# sichtbar würde.
_generating_job_offer_ids: set[int] = set()
_generating_lock = threading.Lock()


@router.get("", response_model=list[ApplicationRead])
def list_applications(db: Session = Depends(get_db)) -> list[Application]:
    """Liefert alle gespeicherten Bewerbungen inkl. zugehörigem Stellenangebot,
    neueste zuerst - Datengrundlage für die Bewerbungsübersicht im Frontend."""
    # `id.desc()` als Tiebreaker: `created_at` hat auf SQLite nur
    # Sekundenauflösung, zwei Bewerbungen innerhalb derselben Sekunde wären
    # sonst nicht stabil sortiert.
    return (
        db.query(Application)
        .options(joinedload(Application.job_offer))
        .order_by(Application.created_at.desc(), Application.id.desc())
        .all()
    )


@router.post("/generate", response_model=ApplicationRead)
def generate_application(payload: ApplicationGenerateRequest, db: Session = Depends(get_db)) -> Application:
    """Generiert ein maßgeschneidertes Anschreiben für ein gespeichertes
    Stellenangebot per KI und speichert das Ergebnis als `Application`.

    Existiert für dieses Stellenangebot bereits eine Bewerbung, wird sie
    neu generiert (Upsert) statt eine doppelte anzulegen.

    Läuft für dieses Stellenangebot bereits eine Generierung (siehe
    `_generating_job_offer_ids`), wird sofort mit 409 abgebrochen statt eine
    zweite, überlappende KI-Generierung zu starten - der Aufrufer (siehe
    `ApplicationEditorComponent.generateForFirstTime`) wartet stattdessen auf
    das Ergebnis der bereits laufenden Generierung.
    """
    job_offer = db.get(JobOffer, payload.job_offer_id)
    if job_offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stellenangebot wurde nicht gefunden.")

    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Es wurde noch kein Profil angelegt. Bitte zunächst über PUT /api/profile anlegen.",
        )

    with _generating_lock:
        if job_offer.id in _generating_job_offer_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Für dieses Stellenangebot läuft bereits eine Generierung. Bitte warten.",
            )
        _generating_job_offer_ids.add(job_offer.id)

    # Vorab geladen (statt erst nach der Generierung wie zuvor), damit ein
    # bereits gespeichertes Anschreiben als `previous_cover_letter_text` an
    # die KI-Generierung weitergereicht werden kann (KTD3, Regenerate-
    # Feature) - dieselbe Zeile wird unten für den Upsert wiederverwendet
    # statt ein zweites Mal abgefragt zu werden.
    application = db.query(Application).filter(Application.job_offer_id == job_offer.id).first()
    previous_cover_letter_text = application.cover_letter_text if application else None

    # `else` statt einem zweiten verschachtelten try/except (ce-code-review-
    # Fund, 2026-08-28): läuft nur, wenn `generate_application_content` NICHT
    # geworfen hat - `finally` gibt die Sperre in jedem Fall frei, aber erst
    # NACH dem DB-Schreiben, nicht schon direkt nach der KI-Generierung
    # (sonst könnte ein Duplikat in die Lücke zwischen Generierung und
    # `db.commit()` hineinlaufen).
    try:
        cover_letter_text = generate_application_content(
            profile, job_offer, previous_cover_letter_text=previous_cover_letter_text
        )
    except ApplicationGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    else:
        if application is None:
            application = Application(job_offer_id=job_offer.id)
            db.add(application)

        application.cover_letter_text = cover_letter_text
        job_offer.is_processed = True
        db.commit()
        db.refresh(application)

        return application
    finally:
        with _generating_lock:
            _generating_job_offer_ids.discard(job_offer.id)


@router.get("/by-job-offer/{job_offer_id}", response_model=ApplicationRead)
def get_application_by_job_offer(job_offer_id: int, db: Session = Depends(get_db)) -> Application:
    """Liefert die zu einem Stellenangebot gehörende Bewerbung (sofern
    bereits generiert), ohne eine neue KI-Generierung anzustoßen.

    Wird vom Editor genutzt, um bei erneutem Aufruf einer bereits
    bearbeiteten Bewerbung keine manuellen Änderungen durch eine erneute
    KI-Generierung zu überschreiben.
    """
    application = db.query(Application).filter(Application.job_offer_id == job_offer_id).first()
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Für dieses Stellenangebot wurde noch keine Bewerbung generiert.",
        )
    return application


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: Session = Depends(get_db)) -> Application:
    """Liefert eine einzelne Bewerbung (z. B. zum Laden im Editor)."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")
    return application


@router.put("/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)
) -> Application:
    """Aktualisiert den Anschreiben-Text einer Bewerbung (z. B. manuelle
    Bearbeitung im Editor) - OHNE die KI erneut aufzurufen, damit manuelle
    Änderungen des Nutzers erhalten bleiben."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(application, field, value)
    db.commit()
    db.refresh(application)

    return application


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: int, db: Session = Depends(get_db)) -> None:
    """Löscht eine Bewerbung unwiderruflich inkl. des zugehörigen
    Stellenangebots.

    `JobOffer.source_url` ist eindeutig (siehe Modell) - bliebe das
    Stellenangebot bestehen, würde ein erneutes Speichern/Generieren für
    denselben Job in `POST /jobs/save` dauerhaft mit 409 fehlschlagen,
    während die Bewerbung selbst nirgends mehr auffindbar wäre. Das Löschen
    des `JobOffer` nimmt die zugehörige `Application` per ORM-Cascade
    (siehe `JobOffer.applications`) automatisch mit.

    P0-Fix (adversarial-reviewer): eine `Application` mit aktivem Portal-
    Auto-Fill-Lauf (`automation_state` "running"/"paused") darf NICHT
    gelöscht werden. Andernfalls könnte z. B. während der pausierten
    `pre_submit_confirmation` die Bewerbung hier gelöscht, danach per
    `continue` trotzdem der echte Submit auf dem externen Portal ausgelöst
    werden - `_record_submission()` fände die (bereits gelöschte)
    `Application`-Zeile dann nicht mehr, und auch `_set_state("failed", ...)`
    liefe ins Leere (No-Op bei fehlender Zeile): eine reale Bewerbung ohne
    jede lokale Spur, ohne Möglichkeit, sie nachträglich als fehlgeschlagen
    zu markieren.
    """
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    if application.automation_state in ("running", "paused"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Diese Bewerbung kann nicht gelöscht werden, während ein Portal-Auto-Fill-Lauf "
                "aktiv ist. Bitte zuerst über den Auto-Fill-Abbruch beenden."
            ),
        )

    job_offer = db.get(JobOffer, application.job_offer_id)
    db.delete(job_offer if job_offer is not None else application)
    db.commit()


@router.post("/{application_id}/send", response_model=ApplicationRead)
def send_application(
    application_id: int, payload: ApplicationSendRequest, db: Session = Depends(get_db)
) -> Application:
    """Versendet die Bewerbung per E-Mail inkl. der im Profil hochgeladenen
    Lebenslauf-Datei als Anhang und markiert sie als `sent`."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    profile = db.query(MasterProfile).first()
    if profile is None or not profile.cv_file_path or not Path(profile.cv_file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Es wurde noch keine Lebenslauf-Datei im Profil hochgeladen - bitte zuerst hochladen.",
        )

    job_offer = db.get(JobOffer, application.job_offer_id)
    default_subject = f"Bewerbung als {job_offer.title}" if job_offer else "Bewerbung"
    subject = payload.subject or default_subject
    body_text = payload.message or (
        "Sehr geehrte Damen und Herren,\n\n"
        "anbei erhalten Sie meinen Lebenslauf zu meiner Bewerbung.\n\n"
        "Für Rückfragen stehe ich gerne zur Verfügung.\n\n"
        "Mit freundlichen Grüßen"
    )
    cv_bytes = Path(profile.cv_file_path).read_bytes()
    # Ein Wert, an zwei Stellen genutzt (Mailversand + SentEmail-Log-Eintrag
    # unten) - einmal berechnet, damit beide nie auseinanderlaufen können.
    attachment_filename = profile.cv_filename or "lebenslauf.pdf"
    # Zusätzliche, im Profil hochgeladene PDF-Anhänge (siehe `ProfileAttachment`,
    # `app.api.profile`) werden neben dem Lebenslauf mitgeschickt. Eine fehlende
    # Datei auf der Festplatte überspringt den jeweiligen Anhang, statt den
    # gesamten Versand abzubrechen (der Lebenslauf bleibt der einzige Pflicht-Anhang).
    extra_attachments = [
        (Path(attachment.file_path).read_bytes(), attachment.filename)
        for attachment in profile.attachments
        if Path(attachment.file_path).exists()
    ]
    # Die vollständige Anhang-Liste in tatsächlicher Versandreihenfolge
    # (Lebenslauf zuerst, danach die zusätzlichen Profil-Anhänge) - für den
    # SentEmail-Log-Eintrag, damit das Protokoll alle Anhänge zeigt, nicht
    # nur den Lebenslauf.
    attachment_filenames = [attachment_filename, *(filename for _, filename in extra_attachments)]

    try:
        used_from_email = send_application_email(
            to_email=payload.to_email,
            subject=subject,
            body_text=body_text,
            attachment_bytes=cv_bytes,
            attachment_filename=attachment_filename,
            extra_attachments=extra_attachments,
            from_email=profile.sender_email,
        )
    except MailSendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    application.status = ApplicationStatus.SENT
    application.sent_at = datetime.now(timezone.utc)
    application.sent_to_email = payload.to_email
    # Protokolliert den Versand als eigenen Log-Eintrag (statt nur die obigen
    # `Application`-Felder zu überschreiben) - siehe R1/R2, KTD2/KTD3,
    # docs/plans/2026-09-14-001-feat-application-email-log-plan.md. Läuft in
    # derselben Transaktion; ein fehlgeschlagener Versand (siehe `except`
    # oben) erzeugt bewusst keinen Eintrag (R3).
    db.add(
        SentEmail(
            application_id=application.id,
            company=job_offer.company if job_offer else None,
            job_title=job_offer.title if job_offer else None,
            source_platform=job_offer.source_platform if job_offer else None,
            recipient_email=payload.to_email,
            sent_at=application.sent_at,
            sender_email=used_from_email,
            subject=subject,
            attachment_filenames=attachment_filenames,
        )
    )
    db.commit()
    db.refresh(application)
    return application
