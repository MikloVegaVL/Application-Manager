"""API-Router für das Master-Profil (Stammdaten, Werdegang, Skills), die
Lebenslauf-Anhang-Datei, das Profilfoto sowie bis zu drei zusätzlichen
PDF-Anhängen fürs E-Mail-Versenden.

Der frühere KI-gestützte CV-Import (`POST /profile/upload-cv`) ist mit U3
entfallen - sein Nachfolger ist der reine Parse-Vorschau-Endpunkt
`POST /cv-builder/parse` (siehe `app.api.cv_builder`), der nichts mehr
direkt in die Datenbank schreibt (R6)."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.master_profile import MasterProfile
from app.models.profile_attachment import ProfileAttachment
from app.schemas.master_profile import MasterProfileCreate, MasterProfileRead, MasterProfileUpdate
from app.services.file_validation import _iter_file, _require_pdf

router = APIRouter(prefix="/profile", tags=["Profile"])

# Detail-Text für alle 404-Fälle "es existiert noch kein `MasterProfile`"
# (siehe u. a. `get_profile`, `update_profile_content`, `upload_cv_file`,
# `upload_photo`, `upload_attachment` unten sowie
# `app.api.cv_builder._render_cv_for_current_profile`) - an einer Stelle
# gepflegt statt als mehrfach dupliziertes String-Literal.
_NO_PROFILE_DETAIL = "Es wurde noch kein Profil angelegt. Bitte zunächst über PUT /api/profile anlegen."

# Maximale Anzahl zusätzlicher PDF-Anhänge (siehe `ProfileAttachment`) - über
# den Lebenslauf hinaus, der weiterhin separat über `cv-file` verwaltet wird.
# Bewusst klein gehalten: die zusätzlichen Anhänge werden 1:1 als weitere
# E-Mail-Anhänge beim Versand einer Bewerbung mitgeschickt
# (`app.api.applications.send_application`), eine unbegrenzte Anzahl würde
# dort unkontrolliert große Mails erzeugen.
MAX_PROFILE_ATTACHMENTS = 3


def _cv_file_path_for(profile_id: int) -> Path:
    # `settings.PROFILE_FILES_DIR` wird bei jedem Aufruf frisch gelesen
    # (statt als Modul-Konstante gecacht), damit Tests es per `monkeypatch`
    # umbiegen können (gleiches Muster wie das frühere `_pdf_path_for` in
    # `app.api.applications`, bevor die Bewerbungs-PDF-Generierung entfiel).
    return Path(settings.PROFILE_FILES_DIR) / f"cv_{profile_id}.pdf"


def _attachment_file_path_for(profile_id: int, attachment_id: int) -> Path:
    # Eigener Dateiname je Anhang (statt eines gemeinsamen Präfixes), damit
    # mehrere Anhänge desselben Profils nicht kollidieren.
    return Path(settings.PROFILE_FILES_DIR) / f"attachment_{profile_id}_{attachment_id}.pdf"


def _photo_path_for(profile_id: int, ext: str) -> Path:
    # Mirrors `_cv_file_path_for` exakt (KTD4) - die Dateiendung ist Teil des
    # Dateinamens, damit ein Formatwechsel (z. B. JPEG -> PNG) unter einem
    # anderen Pfad landet und `upload_photo` die alte Datei erkennen kann.
    return Path(settings.PROFILE_FILES_DIR) / f"photo_{profile_id}.{ext}"


# Erlaubte Profilfoto-Formate (KTD4): Content-Type -> (Magic-Bytes-Präfix,
# Dateiendung). Die Magic-Bytes werden zusätzlich zum Content-Type-Header
# geprüft, da der Header allein vom Client frei gesetzt wird und damit eine
# z. B. als "image/png" deklarierte, tatsächlich andersartige Datei
# durchrutschen könnte.
_IMAGE_FORMATS: dict[str, tuple[bytes, str]] = {
    "image/jpeg": (b"\xff\xd8\xff", "jpg"),
    "image/png": (b"\x89PNG", "png"),
}
_IMAGE_MEDIA_TYPES: dict[str, str] = {ext: content_type for content_type, (_, ext) in _IMAGE_FORMATS.items()}

# 5 MB Obergrenze für Profilfoto-Uploads (KTD4).
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024


def _require_image(file: UploadFile) -> tuple[bytes, str]:
    """Validierung für Profilfoto-Uploads (siehe `_require_pdf` oben für das
    analoge PDF-Pendant): nur JPEG/PNG, per Magic-Bytes gegen den
    Client-Content-Type abgesichert, nicht leer, max. 5 MB (KTD4). Wirft
    `HTTPException` (422) bei Verstoß, sonst (gelesene Bytes, Dateiendung)."""
    image_format = _IMAGE_FORMATS.get(file.content_type or "")
    if image_format is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nur JPEG- oder PNG-Bilder werden unterstützt.",
        )
    magic_bytes, ext = image_format

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Die hochgeladene Datei ist leer.",
        )
    if len(file_bytes) > MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Die Datei ist zu groß (maximal 5 MB).",
        )
    if not file_bytes.startswith(magic_bytes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Der Dateiinhalt entspricht nicht dem angegebenen Bildformat.",
        )

    return file_bytes, ext


@router.get("", response_model=MasterProfileRead)
def get_profile(db: Session = Depends(get_db)) -> MasterProfile:
    """Liefert das Master-Profil. Die Anwendung ist für den persönlichen
    Gebrauch konzipiert, es existiert daher maximal ein Profil-Datensatz."""
    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_PROFILE_DETAIL,
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


# Identitätsfelder bleiben exklusiv `PUT /profile` vorbehalten (KTD2) - der
# CV-Builder darf sie über `PATCH /profile` nicht mitändern, selbst wenn er
# sie (versehentlich) im Payload mitschickt.
_IDENTITY_FIELDS = {"full_name", "email", "phone", "address"}


@router.patch("", response_model=MasterProfileRead)
def update_profile_content(payload: MasterProfileUpdate, db: Session = Depends(get_db)) -> MasterProfile:
    """Partielles Update der CV-Builder-Inhaltsfelder (R2/R3/R4, KTD2).

    Anders als `PUT /profile` (Upsert, vollständiges Überschreiben) ist dies
    ein echtes partielles Update: nur die im Payload tatsächlich gesetzten
    Felder werden geändert (`exclude_unset`), fehlende Felder bleiben
    unangetastet. Identitätsfelder (`full_name`, `email`, `phone`, `address`)
    bleiben `PUT` vorbehalten und werden hier mit 422 abgelehnt, sofern sie
    nicht-null im Payload stehen. `photo_path` ist in `MasterProfileUpdate`
    gar nicht erst enthalten - das schreiben ausschließlich die
    Foto-Endpunkte (`POST`/`DELETE /profile/photo`).

    Setzt ein bereits existierendes Profil voraus (KTD9): der Builder legt
    kein neues Profil an, das bleibt weiterhin `PUT /profile` vorbehalten.
    """
    data = payload.model_dump(exclude_unset=True)

    identity_violations = [field for field in _IDENTITY_FIELDS if data.get(field) is not None]
    if identity_violations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Identitätsfelder (full_name, email, phone, address) können nicht über "
                f"PATCH /profile geändert werden: {', '.join(sorted(identity_violations))}. "
                "Bitte PUT /api/profile verwenden."
            ),
        )

    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_PROFILE_DETAIL,
        )

    for field, value in data.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


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
            detail=_NO_PROFILE_DETAIL,
        )

    file_bytes = _require_pdf(file)

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

    filename = profile.cv_filename or "lebenslauf.pdf"
    return StreamingResponse(
        _iter_file(cv_path),
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


# --- Profilfoto (JPEG/PNG, siehe KTD4) -----------------------------------
#
# Mirrors `cv-file` oben exakt, nur mit Bild- statt PDF-Validierung
# (`_require_image` statt `_require_pdf`) und dateiendungsabhängigem
# Speicherpfad, da JPEG/PNG anders als das feste PDF-Format zwei mögliche
# Endungen zulässt.


@router.post("/photo", response_model=MasterProfileRead)
def upload_photo(
    file: UploadFile = File(..., description="Profilfoto als JPEG- oder PNG-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Speichert ein Profilfoto fürs Stammprofil (CV-Builder, R3).

    Ein bereits existierendes Profil ist Voraussetzung, da die Datei am
    Profil hängt. Wechselt das Bildformat gegenüber einem bereits
    vorhandenen Foto (z. B. JPEG -> PNG), wird die alte Datei zuerst entfernt,
    damit keine verwaiste Datei unter der alten Endung zurückbleibt; ein
    Re-Upload im selben Format überschreibt die vorhandene Datei einfach
    (wie bei `cv-file`).
    """
    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_PROFILE_DETAIL,
        )

    file_bytes, ext = _require_image(file)
    photo_path = _photo_path_for(profile.id, ext)

    if profile.photo_path:
        old_path = Path(profile.photo_path)
        if old_path != photo_path and old_path.exists():
            old_path.unlink()

    photo_path.parent.mkdir(parents=True, exist_ok=True)
    photo_path.write_bytes(file_bytes)

    profile.photo_path = str(photo_path)
    profile.photo_filename = file.filename or f"foto.{ext}"
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/photo")
def download_photo(db: Session = Depends(get_db)) -> StreamingResponse:
    """Liefert das hochgeladene Profilfoto zurück (z. B. für die Vorschau im
    CV-Builder)."""
    profile = db.query(MasterProfile).first()
    if profile is None or not profile.photo_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Es wurde noch kein Profilfoto hochgeladen.",
        )

    photo_path = Path(profile.photo_path)
    if not photo_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profilfoto-Datei wurde nicht gefunden.")

    media_type = _IMAGE_MEDIA_TYPES.get(photo_path.suffix.lstrip("."), "application/octet-stream")
    filename = profile.photo_filename or photo_path.name
    return StreamingResponse(
        _iter_file(photo_path),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/photo", response_model=MasterProfileRead)
def delete_photo(db: Session = Depends(get_db)) -> MasterProfile:
    """Entfernt das hochgeladene Profilfoto wieder (z. B. um es durch ein
    anderes zu ersetzen)."""
    profile = db.query(MasterProfile).first()
    if profile is None or not profile.photo_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Es wurde noch kein Profilfoto hochgeladen.",
        )

    photo_path = Path(profile.photo_path)
    if photo_path.exists():
        photo_path.unlink()

    profile.photo_path = None
    profile.photo_filename = None
    db.commit()
    db.refresh(profile)
    return profile


# --- Zusätzliche Anhänge (bis zu MAX_PROFILE_ATTACHMENTS PDFs) ----------
#
# Getrennt vom Lebenslauf-Anhang oben: diese Dateien werden beim Versand
# einer Bewerbung zusätzlich zum Lebenslauf angehängt (siehe
# `app.api.applications.send_application`), nicht anstelle davon.


@router.post("/attachments", response_model=MasterProfileRead)
def upload_attachment(
    file: UploadFile = File(..., description="Zusätzlicher Anhang als PDF-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Fügt dem Profil einen weiteren PDF-Anhang hinzu (z. B. Arbeitszeugnis,
    Zertifikat), der beim Versand einer Bewerbung zusätzlich zum Lebenslauf
    mitgeschickt wird. Auf `MAX_PROFILE_ATTACHMENTS` begrenzt - ein bereits
    existierendes Profil ist Voraussetzung, da die Anhänge am Profil hängen."""
    profile = db.query(MasterProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_PROFILE_DETAIL,
        )

    if len(profile.attachments) >= MAX_PROFILE_ATTACHMENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Es können maximal {MAX_PROFILE_ATTACHMENTS} zusätzliche Anhänge hochgeladen werden.",
        )

    file_bytes = _require_pdf(file)

    attachment = ProfileAttachment(profile_id=profile.id, filename=file.filename or "anhang.pdf", file_path="")
    db.add(attachment)
    db.flush()  # vergibt attachment.id, ohne die Transaktion schon zu committen

    attachment_path = _attachment_file_path_for(profile.id, attachment.id)
    attachment_path.parent.mkdir(parents=True, exist_ok=True)
    attachment_path.write_bytes(file_bytes)
    attachment.file_path = str(attachment_path)

    db.commit()
    db.refresh(profile)
    return profile


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    """Liefert einen einzelnen zusätzlichen Anhang zurück (z. B. für eine
    Vorschau/Download-Prüfung im Profil-Frontend)."""
    attachment = db.get(ProfileAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anhang wurde nicht gefunden.")

    attachment_path = Path(attachment.file_path)
    if not attachment_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anhang-Datei wurde nicht gefunden.")

    return StreamingResponse(
        _iter_file(attachment_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{attachment.filename}"'},
    )


@router.delete("/attachments/{attachment_id}", response_model=MasterProfileRead)
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)) -> MasterProfile:
    """Entfernt einen zusätzlichen Anhang wieder (z. B. um Platz für einen
    anderen zu schaffen, da auf MAX_PROFILE_ATTACHMENTS begrenzt)."""
    attachment = db.get(ProfileAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anhang wurde nicht gefunden.")

    profile = attachment.profile
    attachment_path = Path(attachment.file_path)
    if attachment_path.exists():
        attachment_path.unlink()

    db.delete(attachment)
    db.commit()
    db.refresh(profile)
    return profile
