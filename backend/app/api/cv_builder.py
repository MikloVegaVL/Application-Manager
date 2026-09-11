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
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.profile import _require_pdf
from app.schemas.master_profile import CvParseResponse
from app.services.pdf_parser import CvAnalysisError, PdfParsingError, missing_field_warnings, parse_cv_pdf

router = APIRouter(prefix="/cv-builder", tags=["CV Builder"])


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
