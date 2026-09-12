"""API-Router für die reine CV-Parse-Vorschau des CV-Builders (R5-R8).

Nimmt eine Lebenslauf-PDF entgegen, lässt die KI sie strukturieren und
liefert das Ergebnis unverändert zurück, OHNE irgendetwas in die Datenbank
zu schreiben - das Speichern übernimmt ausschließlich der spätere, explizite
Save-Schritt des Builder-Formulars (R6/KTD1).

Ersetzt das frühere `POST /profile/upload-cv` (Auto-Merge-Endpunkt aus der
Ollama-Migration): Jener Endpunkt schrieb Parse-Ergebnisse direkt ins
Stammprofil und wurde mit dem Wechsel von `skills: list[str]` zu
`skills_json: list[SkillEntry]` (KTD3) inkompatibel. Da der CV-Builder
(R5/R6) ohnehin ein reines Vorschau-Formular verlangt statt eines
automatischen Merges, wurde der alte Endpunkt ersatzlos entfernt statt
repariert - dieser Router ist sein vollständiger Ersatz.
"""
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.profile import _NO_PROFILE_DETAIL
from app.db.database import get_db
from app.models.master_profile import MasterProfile
from app.schemas.master_profile import (
    CvParseResponse,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
    SkillEntry,
)
from app.services.file_validation import _require_pdf
from app.services.pdf_parser import CvAnalysisError, PdfParsingError, missing_field_warnings, parse_cv_pdf
from app.services.pdf_service import CV_TEMPLATES, CvTemplateId, PdfRenderError, render_cv_pdf

router = APIRouter(prefix="/cv-builder", tags=["CV Builder"])


class CvRenderRequest(BaseModel):
    """Payload für `POST /cv-builder/preview` und `.../export` (KTD11): die
    aktuellen CV-Builder-Formularinhalte des Frontends - inklusive etwaiger
    noch nicht gespeicherter Änderungen (R10/R11), daher bewusst NICHT aus
    der Datenbank gelesen, sondern 1:1 aus dem Request-Body übernommen.

    Identitätsfelder (`full_name`/`email`/`phone`/`address`) sind bewusst
    NICHT Teil dieses Bodys (KTD11): Preview/Export mergen sie serverseitig
    aus dem gespeicherten `MasterProfile`-Datensatz. Das tatsächliche Foto
    ebenso: `photo_filename` steht hier nur der Payload-Symmetrie mit
    `MasterProfileUpdate` wegen - das Foto wird, anders als Textfelder,
    sofort beim Upload persistiert (`POST /profile/photo`), es gibt also nie
    einen "unsaved" Fotozustand. Gerendert wird daher immer das im
    gespeicherten Profil hinterlegte Foto (`MasterProfile.photo_path`), nicht
    dieses Feld.
    """

    template_id: CvTemplateId
    summary: str | None = None
    berufsbezeichnung: str | None = None
    experiences_json: list[ExperienceEntry] = Field(default_factory=list)
    education_json: list[EducationEntry] = Field(default_factory=list)
    skills_json: list[SkillEntry] = Field(default_factory=list)
    languages_json: list[LanguageEntry] = Field(default_factory=list)
    projects_json: list[ProjectEntry] = Field(default_factory=list)
    photo_filename: str | None = None


def _sanitize_filename_component(value: str) -> str:
    """Ersetzt für Dateinamen unsichere Zeichen (Leerzeichen, Slashes, etc.)
    durch `_`, für den `Content-Disposition`-Dateinamen von
    `POST /cv-builder/export`. Nur ASCII-Buchstaben/Ziffern/`_`/`-` bleiben
    erhalten - `Content-Disposition`-Header dürfen keine Nicht-ASCII-Bytes
    unkodiert enthalten (z. B. Umlaute), daher werden auch diese ersetzt statt
    nur klassische Pfadtrenner."""
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return sanitized.strip("_") or "lebenslauf"


def _render_cv_for_current_profile(
    payload: CvRenderRequest, db: Session, *, preview: bool
) -> tuple[bytes, MasterProfile]:
    """Gemeinsame Implementierung für `preview`/`export` (KTD11): lädt das
    gespeicherte Profil (404, falls keins existiert - KTD9), mergt dessen
    Identitätsfelder und Foto mit dem Request-Body und rendert das PDF."""
    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NO_PROFILE_DETAIL)

    try:
        pdf_bytes = render_cv_pdf(
            template_id=payload.template_id,
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            address=profile.address,
            summary=payload.summary,
            berufsbezeichnung=payload.berufsbezeichnung,
            experiences=payload.experiences_json,
            education=payload.education_json,
            skills=payload.skills_json,
            languages=payload.languages_json,
            projects=payload.projects_json,
            photo_path=profile.photo_path,
            preview=preview,
        )
    except PdfRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lebenslauf konnte nicht als PDF erzeugt werden: {exc}",
        ) from exc

    return pdf_bytes, profile


@router.post("/parse", response_model=CvParseResponse)
def parse_cv(file: UploadFile = File(..., description="Lebenslauf als PDF-Datei")) -> CvParseResponse:
    """Analysiert eine Lebenslauf-PDF per KI und liefert das Ergebnis
    ausschließlich als Vorschlag für das Builder-Formular zurück.

    Kein Datenbankzugriff: Weder wird ein bestehendes Profil gelesen noch
    geschrieben (R6) - das Ergebnis befüllt im Frontend nur die Formularfelder,
    nichts wird bis zum expliziten Save des Nutzers persistiert. Name- und
    Kontaktfelder (`full_name`/`email`/`phone`/`address`) dienen im Formular
    ausdrücklich nur der Anzeige (read-only, KTD1) und werden vom
    Builder-Save-Payload ohnehin ignoriert.

    Bewusst OHNE Foto- oder Kompetenzgrad-Ableitung (R7) - beides bleibt
    vollständig dem Nutzer im Formular überlassen. Nur PDF wird akzeptiert
    (R8, siehe `_require_pdf`); DOCX o. ä. ist out of scope.
    """
    file_bytes = _require_pdf(file)

    try:
        parsed = parse_cv_pdf(file_bytes)
    except PdfParsingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except CvAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return CvParseResponse(parsed=parsed, warnings=missing_field_warnings(parsed))


@router.get("/templates")
def list_templates() -> list[dict[str, str]]:
    """Liefert die kleine, feste Auswahl wählbarer visueller CV-Vorlagen
    (R9) - dieselbe Liste, gegen die `CvRenderRequest.template_id` validiert
    wird (siehe `app.services.pdf_service.CV_TEMPLATES`)."""
    return CV_TEMPLATES


@router.post("/preview")
def preview_cv(payload: CvRenderRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    """Rendert den Lebenslauf aus dem aktuellen (ggf. ungespeicherten)
    Formularinhalt als PDF und liefert es inline zur Anzeige im Browser
    (R10, KTD7: dieselbe Rendering-Pipeline wie der Export, kein separates
    Live-HTML/CSS-Preview-Template)."""
    pdf_bytes, _profile = _render_cv_for_current_profile(payload, db, preview=True)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="lebenslauf-vorschau.pdf"'},
    )


@router.post("/export")
def export_cv(payload: CvRenderRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    """Rendert den Lebenslauf aus dem aktuellen Formularinhalt als PDF und
    liefert es als Download (R11)."""
    pdf_bytes, profile = _render_cv_for_current_profile(payload, db, preview=False)
    filename = f"lebenslauf_{_sanitize_filename_component(profile.full_name)}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
