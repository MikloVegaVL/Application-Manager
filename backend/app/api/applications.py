"""API-Router für Bewerbungen: KI-Generierung, PDF-Auslieferung und Mailversand."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.database import get_db
from app.models.application import Application, ApplicationStatus
from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.schemas.application import (
    ApplicationGenerateRequest,
    ApplicationRead,
    ApplicationSendRequest,
    ApplicationUpdate,
)
from app.schemas.generation import TailoredCv
from app.services.ai_generator import ApplicationGenerationError, generate_application_content
from app.services.mail_service import MailSendError, send_application_email
from app.services.pdf_service import PdfRenderError, render_application_pdf

router = APIRouter(prefix="/applications", tags=["Applications"])


def _pdf_path_for(application_id: int) -> Path:
    return Path(settings.GENERATED_FILES_DIR) / f"application_{application_id}.pdf"


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
    """Generiert eine maßgeschneiderte Bewerbung (Anschreiben + Lebenslauf)
    für ein gespeichertes Stellenangebot per KI, rendert sie als PDF und
    speichert das Ergebnis als `Application`.

    Existiert für dieses Stellenangebot bereits eine Bewerbung, wird sie
    neu generiert (Upsert) statt eine doppelte anzulegen.
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

    try:
        cover_letter_text, tailored_cv = generate_application_content(profile, job_offer)
    except ApplicationGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        pdf_bytes = render_application_pdf(cover_letter_text, tailored_cv, job_offer)
    except PdfRenderError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    application = db.query(Application).filter(Application.job_offer_id == job_offer.id).first()
    if application is None:
        application = Application(job_offer_id=job_offer.id)
        db.add(application)

    application.cover_letter_text = cover_letter_text
    application.tailored_cv_json = tailored_cv.model_dump()
    db.commit()
    db.refresh(application)

    pdf_path = _pdf_path_for(application.id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)
    application.pdf_path = str(pdf_path)

    job_offer.is_processed = True
    db.commit()
    db.refresh(application)

    return application


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
    """Aktualisiert Anschreiben- und/oder Lebenslauf-Inhalte einer Bewerbung
    (z. B. manuelle Bearbeitung im Editor) und rendert das PDF aus dem
    bearbeiteten Inhalt neu - OHNE die KI erneut aufzurufen, damit manuelle
    Änderungen des Nutzers erhalten bleiben."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(application, field, value)
    db.commit()
    db.refresh(application)

    if "cover_letter_text" in data or "tailored_cv_json" in data:
        job_offer = db.get(JobOffer, application.job_offer_id)
        if job_offer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Zugehöriges Stellenangebot wurde nicht gefunden.",
            )
        if not application.tailored_cv_json:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Es liegen keine Lebenslauf-Daten vor - bitte zunächst über /generate erzeugen.",
            )

        try:
            tailored_cv = TailoredCv.model_validate(application.tailored_cv_json)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Lebenslauf-Daten sind ungültig: {exc}",
            ) from exc

        try:
            pdf_bytes = render_application_pdf(application.cover_letter_text or "", tailored_cv, job_offer)
        except PdfRenderError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

        pdf_path = _pdf_path_for(application.id)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(pdf_bytes)
        application.pdf_path = str(pdf_path)
        db.commit()
        db.refresh(application)

    return application


@router.get("/{application_id}/pdf")
def get_application_pdf(application_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    """Liefert die generierte PDF-Datei der Bewerbung als Stream zurück."""
    application = db.get(Application, application_id)
    if application is None or not application.pdf_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Für diese Bewerbung wurde noch keine PDF erzeugt.",
        )

    pdf_path = Path(application.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF-Datei wurde nicht gefunden.")

    def iter_pdf_file(path: Path, chunk_size: int = 65_536):
        with path.open("rb") as file:
            while chunk := file.read(chunk_size):
                yield chunk

    return StreamingResponse(
        iter_pdf_file(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="bewerbung_{application_id}.pdf"'},
    )


@router.post("/{application_id}/send", response_model=ApplicationRead)
def send_application(
    application_id: int, payload: ApplicationSendRequest, db: Session = Depends(get_db)
) -> Application:
    """Versendet die generierte Bewerbung per E-Mail inkl. PDF-Anhang und
    markiert sie als `sent`."""
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bewerbung wurde nicht gefunden.")

    if not application.pdf_path or not Path(application.pdf_path).exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Für diese Bewerbung liegt noch keine PDF vor - bitte zuerst generieren.",
        )

    job_offer = db.get(JobOffer, application.job_offer_id)
    default_subject = f"Bewerbung als {job_offer.title}" if job_offer else "Bewerbung"
    subject = payload.subject or default_subject
    body_text = payload.message or (
        "Sehr geehrte Damen und Herren,\n\n"
        "anbei erhalten Sie meine Bewerbungsunterlagen (Anschreiben und Lebenslauf).\n\n"
        "Für Rückfragen stehe ich gerne zur Verfügung.\n\n"
        "Mit freundlichen Grüßen"
    )
    pdf_bytes = Path(application.pdf_path).read_bytes()

    try:
        send_application_email(
            to_email=payload.to_email,
            subject=subject,
            body_text=body_text,
            attachment_bytes=pdf_bytes,
            attachment_filename=f"bewerbung_{application_id}.pdf",
        )
    except MailSendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    application.status = ApplicationStatus.SENT
    application.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(application)
    return application
