"""API-Router für das Master-Profil (Stammdaten, Werdegang, Skills) inkl.
KI-gestütztem CV-Import."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.master_profile import MasterProfile
from app.schemas.master_profile import MasterProfileCreate, MasterProfileRead
from app.services.pdf_parser import CvAnalysisError, PdfParsingError, parse_cv_pdf

router = APIRouter(prefix="/profile", tags=["Profile"])


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


@router.post("/upload-cv", response_model=MasterProfileRead)
def upload_cv(
    file: UploadFile = File(..., description="Lebenslauf als PDF-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Nimmt eine Lebenslauf-PDF entgegen, extrahiert den Text und lässt GPT-4o
    daraus ein strukturiertes Profil ableiten.

    Existiert noch kein Profil, wird eines angelegt (dafür müssen mindestens
    Name und E-Mail aus dem CV extrahierbar sein). Existiert bereits ein
    Profil, werden nur Felder überschrieben/ergänzt, die die KI tatsächlich
    im Lebenslauf gefunden hat - vorhandene Daten gehen nicht verloren.
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
    return profile
