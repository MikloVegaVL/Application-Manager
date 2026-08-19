"""API-Router für das Master-Profil (Stammdaten, Werdegang, Skills) inkl.
KI-gestütztem CV-Import und der Lebenslauf-Anhang-Datei fürs E-Mail-Versenden."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.master_profile import MasterProfile
from app.schemas.master_profile import CvUploadResponse, MasterProfileCreate, MasterProfileRead
from app.services.pdf_parser import CvAnalysisError, ParsedCvProfile, PdfParsingError, parse_cv_pdf

router = APIRouter(prefix="/profile", tags=["Profile"])


def _cv_file_path_for(profile_id: int) -> Path:
    # `settings.PROFILE_FILES_DIR` wird bei jedem Aufruf frisch gelesen
    # (statt als Modul-Konstante gecacht), damit Tests es per `monkeypatch`
    # umbiegen können (gleiches Muster wie das frühere `_pdf_path_for` in
    # `app.api.applications`, bevor die Bewerbungs-PDF-Generierung entfiel).
    return Path(settings.PROFILE_FILES_DIR) / f"cv_{profile_id}.pdf"

# Felder, für die eine leere KI-Antwort dem Nutzer als Warnung gemeldet wird
# (siehe CvUploadResponse.warnings) - bewusst nur die inhaltlich substanziellen
# Felder, nicht Telefon/Adresse, die auf vielen Lebensläufen legitim fehlen.
_WARNING_LABELS: dict[str, str] = {
    "summary": "Kein Kurzprofil/Zusammenfassung gefunden.",
    "experiences": "Keine Berufserfahrung gefunden - vorhandene Angaben blieben unverändert.",
    "education": "Keine Ausbildung gefunden - vorhandene Angaben blieben unverändert.",
    "skills": "Keine Skills gefunden.",
}


def _missing_field_warnings(parsed: ParsedCvProfile) -> list[str]:
    """Baut die Warnungsliste für `CvUploadResponse` (siehe ce-debug-
    Untersuchung, 2026-08-18): `upload_cv` übernimmt ein Feld nur, wenn die KI
    dafür etwas gefunden hat, damit ein unvollständiger Parse ein bereits
    gepflegtes Profil nicht mit leeren Werten überschreibt - das blieb bisher
    aber komplett unsichtbar für den Nutzer, der einen unbedingten Erfolg
    sah, obwohl z. B. keine Berufserfahrung übernommen wurde."""
    return [message for field, message in _WARNING_LABELS.items() if not getattr(parsed, field)]


@router.get("", response_model=MasterProfileRead)
def get_profile(db: Session = Depends(get_db)) -> MasterProfile:
    """Liefert das Master-Profil. Die Anwendung ist für den persönlichen
    Gebrauch konzipiert, es existiert daher maximal ein Profil-Datensatz."""
    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Es wurde noch kein Profil angelegt. Bitte zunächst über PUT /api/profile anlegen.",
        )
    return profile


@router.put("", response_model=MasterProfileRead)
def upsert_profile(payload: MasterProfileCreate, db: Session = Depends(get_db)) -> MasterProfile:
    """Erstellt das Master-Profil beim ersten Aufruf oder überschreibt es
    vollständig mit den übergebenen Daten (Upsert-Semantik)."""
    profile = db.query(MasterProfile).first()
    data = payload.model_dump()

    if profile is None:
        profile = MasterProfile(**data)
        db.add(profile)
    else:
        for field, value in data.items():
            setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


@router.post("/upload-cv", response_model=CvUploadResponse)
def upload_cv(
    file: UploadFile = File(..., description="Lebenslauf als PDF-Datei"),
    db: Session = Depends(get_db),
) -> CvUploadResponse:
    """Nimmt eine Lebenslauf-PDF entgegen, extrahiert den Text und lässt die KI
    (via Ollama) daraus ein strukturiertes Profil ableiten.

    Existiert noch kein Profil, wird eines angelegt (dafür müssen mindestens
    Name und E-Mail aus dem CV extrahierbar sein). Existiert bereits ein
    Profil, werden nur Felder überschrieben/ergänzt, die die KI tatsächlich
    im Lebenslauf gefunden hat - vorhandene Daten gehen nicht verloren, aber
    die Antwort benennt in `warnings`, welche Felder deshalb NICHT übernommen
    wurden (siehe CvUploadResponse).
    """
    is_pdf = file.content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Nur PDF-Dateien werden unterstützt.",
        )

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die hochgeladene Datei ist leer.",
        )

    try:
        parsed = parse_cv_pdf(file_bytes)
    except PdfParsingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except CvAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    profile = db.query(MasterProfile).first()

    if profile is None:
        if not parsed.full_name or not parsed.email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Aus dem Lebenslauf konnten Name und/oder E-Mail-Adresse nicht "
                    "extrahiert werden. Bitte lege das Profil zunächst manuell über "
                    "PUT /api/profile an."
                ),
            )
        profile = MasterProfile(full_name=parsed.full_name, email=parsed.email)
        db.add(profile)

    # Vorhandene Daten nur ergänzen/überschreiben, wenn die KI dafür etwas
    # gefunden hat - ein unvollständig gelesener CV darf ein bereits
    # gepflegtes Profil nicht mit leeren Werten überschreiben.
    if parsed.full_name:
        profile.full_name = parsed.full_name
    if parsed.email:
        profile.email = parsed.email
    if parsed.phone:
        profile.phone = parsed.phone
    if parsed.address:
        profile.address = parsed.address
    if parsed.summary:
        profile.summary = parsed.summary
    if parsed.experiences:
        profile.experiences_json = [entry.model_dump() for entry in parsed.experiences]
    if parsed.education:
        profile.education_json = [entry.model_dump() for entry in parsed.education]
    if parsed.skills:
        # Bestehende und neue Skills zusammenführen, Duplikate entfernen,
        # Reihenfolge (erstes Vorkommen) bleibt stabil erhalten.
        merged_skills = list(dict.fromkeys([*(profile.skills_json or []), *parsed.skills]))
        profile.skills_json = merged_skills

    db.commit()
    db.refresh(profile)
    return CvUploadResponse(profile=profile, warnings=_missing_field_warnings(parsed))


@router.post("/cv-file", response_model=MasterProfileRead)
def upload_cv_file(
    file: UploadFile = File(..., description="Lebenslauf als PDF-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Speichert eine Lebenslauf-PDF unverändert (kein KI-Parsing, kein
    Rendering) als Anhang-Datei fürs Profil.

    Anders als `POST /profile/upload-cv` wird diese Datei nicht analysiert,
    um Profilfelder zu befüllen - sie wird 1:1 als E-Mail-Anhang verwendet,
    wenn eine Bewerbung versendet wird (`POST /applications/{id}/send`).
    Ein bereits existierendes Profil ist Voraussetzung, da die Datei am
    Profil hängt.
    """
    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Es wurde noch kein Profil angelegt. Bitte zunächst über PUT /api/profile anlegen.",
        )

    is_pdf = file.content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Nur PDF-Dateien werden unterstützt.",
        )

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die hochgeladene Datei ist leer.",
        )

    cv_path = _cv_file_path_for(profile.id)
    cv_path.parent.mkdir(parents=True, exist_ok=True)
    cv_path.write_bytes(file_bytes)

    profile.cv_file_path = str(cv_path)
    profile.cv_filename = file.filename or "lebenslauf.pdf"
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/cv-file")
def download_cv_file(db: Session = Depends(get_db)) -> StreamingResponse:
    """Liefert die hochgeladene Lebenslauf-Anhang-Datei zurück (z. B. für
    eine Vorschau/Download-Prüfung im Profil-Frontend)."""
    profile = db.query(MasterProfile).first()
    if profile is None or not profile.cv_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Es wurde noch keine Lebenslauf-Datei hochgeladen.",
        )

    cv_path = Path(profile.cv_file_path)
    if not cv_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lebenslauf-Datei wurde nicht gefunden.")

    def iter_cv_file(path: Path, chunk_size: int = 65_536):
        with path.open("rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    filename = profile.cv_filename or "lebenslauf.pdf"
    return StreamingResponse(
        iter_cv_file(cv_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/cv-file", response_model=MasterProfileRead)
def delete_cv_file(db: Session = Depends(get_db)) -> MasterProfile:
    """Entfernt die hochgeladene Lebenslauf-Anhang-Datei wieder (z. B. um sie
    durch eine andere zu ersetzen)."""
    profile = db.query(MasterProfile).first()
    if profile is None or not profile.cv_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Es wurde noch keine Lebenslauf-Datei hochgeladen.",
        )

    cv_path = Path(profile.cv_file_path)
    if cv_path.exists():
        cv_path.unlink()

    profile.cv_file_path = None
    profile.cv_filename = None
    db.commit()
    db.refresh(profile)
    return profile
