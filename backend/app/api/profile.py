"""API-Router für das Master-Profil (Stammdaten, Werdegang, Skills), die
Lebenslauf-Anhang-Datei, das Profilfoto sowie bis zu drei zusätzlichen
PDF-Anhänge fürs E-Mail-Versenden.

Der frühere KI-gestützte CV-Import (`POST /profile/upload-cv`) ist mit U3
entfallen - sein Nachfolger ist der reine Parse-Vorschau-Endpunkt
`POST /cv-builder/parse` (siehe `app.api.cv_builder`), der nichts mehr
direkt in die Datenbank schreibt (R6).

Mit U2 (docs/plans/2026-09-23-001-feat-profile-types-plan.md) trägt jeder
Endpunkt zusätzlich einen `profile_type`-Pfadparameter (`it`/`full_life`,
KTD1): die Anwendung unterhält jetzt zwei vollständig unabhängige Profile
(R1/R2/R3) statt eines einzigen `MasterProfile`-Datensatzes."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.master_profile import MasterProfile
from app.models.profile_attachment import ProfileAttachment
from app.schemas.master_profile import MasterProfileCreate, MasterProfileRead, MasterProfileUpdate, ProfileType
from app.services.file_validation import _iter_file, _require_pdf

router = APIRouter(prefix="/profile", tags=["Profile"])

# Anzeigename je Profiltyp fürs 404-Detail (`_get_profile_or_404` unten) -
# damit die Fehlermeldung das konkrete Profil benennt statt generisch zu
# bleiben.
_PROFILE_TYPE_LABELS: dict[str, str] = {"it": "IT", "full_life": "Full-life/Non-IT"}

# Detail-Text-Vorlage für alle 404-Fälle "es existiert noch kein Profil
# dieses Typs" (siehe `_get_profile_or_404` unten) - an einer Stelle
# gepflegt statt als mehrfach dupliziertes String-Literal.
_NO_PROFILE_DETAIL_TEMPLATE = (
    "Es wurde noch kein {label}-Profil angelegt. Bitte zunächst über PUT /api/profile/{profile_type} anlegen."
)

# Maximale Anzahl zusätzlicher PDF-Anhänge (siehe `ProfileAttachment`) - über
# den Lebenslauf hinaus, der weiterhin separat über `cv-file` verwaltet wird.
# Bewusst klein gehalten: die zusätzlichen Anhänge werden 1:1 als weitere
# E-Mail-Anhänge beim Versand einer Bewerbung mitgeschickt
# (`app.api.applications.send_application`), eine unbegrenzte Anzahl würde
# dort unkontrolliert große Mails erzeugen.
MAX_PROFILE_ATTACHMENTS = 3


def _get_profile_or_404(db: Session, profile_type: ProfileType) -> MasterProfile:
    """Löst den `MasterProfile`-Datensatz für den gegebenen `profile_type`
    auf (KTD6: ersetzt die zuvor zehnfach duplizierten
    `db.query(MasterProfile).first()` + 404-Blöcke). Jedes Profil ist über
    seinen `profile_type` eindeutig (siehe `uq_master_profiles_profile_type`
    auf `MasterProfile`), daher genügt ein `filter_by` statt `.first()` auf
    der gesamten Tabelle."""
    profile = db.query(MasterProfile).filter_by(profile_type=profile_type).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_PROFILE_DETAIL_TEMPLATE.format(
                label=_PROFILE_TYPE_LABELS[profile_type], profile_type=profile_type
            ),
        )
    return profile


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


# --- Erstmalige Migration der untypisierten Alt-Zeile (U6, R8/KTD7) ------
#
# Anders als alle Routen oben/unten sind diese zwei NICHT auf einen
# `profile_type` skaliert - sie handeln vom (höchstens einen) alten
# `MasterProfile`-Datensatz mit `profile_type IS NULL` (Datenstand vor U1).
# Deshalb müssen sie als statische Pfade VOR `GET /{profile_type}` registriert
# sein, sonst würde Starlette "migration-status"/"migrate" fälschlich als
# `profile_type`-Pfadparameter interpretieren. KTD7: es gibt bewusst kein
# eigenes "Migration erledigt"-Flag - der Zustand ergibt sich allein aus
# `profile_type IS NULL`; ein abgebrochener Migrationsversuch hinterlässt
# einfach weiterhin eine untypisierte Zeile, der Prompt erscheint dann beim
# nächsten Laden erneut, ohne dass zusätzlich etwas nachgeführt werden müsste.


class MigrationStatusResponse(BaseModel):
    """Antwort von `GET /profile/migration-status` (R8)."""

    has_untyped_profile: bool


class ProfileMigrationRequest(BaseModel):
    """Payload für `POST /profile/migrate`."""

    profile_type: ProfileType


@router.get("/migration-status", response_model=MigrationStatusResponse)
def get_migration_status(db: Session = Depends(get_db)) -> MigrationStatusResponse:
    """Meldet, ob noch eine untypisierte Alt-Zeile (`profile_type IS NULL`)
    existiert. Das Frontend zeigt den einmaligen Migrations-Prompt (R8) genau
    dann, wenn `has_untyped_profile` true ist - sowohl auf einer frischen
    Installation (gar keine Zeile vorhanden) als auch nach erfolgreicher
    Migration ist das false, der Prompt bleibt dann aus."""
    has_untyped_profile = db.query(MasterProfile).filter_by(profile_type=None).first() is not None
    return MigrationStatusResponse(has_untyped_profile=has_untyped_profile)


@router.post("/migrate", response_model=MasterProfileRead)
def migrate_profile(payload: ProfileMigrationRequest, db: Session = Depends(get_db)) -> MasterProfile:
    """Ordnet die untypisierte Alt-Zeile (`profile_type IS NULL`) einmalig
    einem der beiden Profiltypen zu (R8) - eine explizite Nutzerentscheidung
    statt einer stillen Auto-Zuordnung, da sich die beiden Profile im
    Nachhinein nur schwer wieder trennen ließen (Product Contract Key
    Decision). 409, falls keine untypisierte Zeile (mehr) existiert - entweder
    wurde bereits migriert, oder es gibt auf einer frischen Installation
    ohnehin noch gar keine Profil-Zeile."""
    profile = db.query(MasterProfile).filter_by(profile_type=None).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Es existiert kein untypisiertes Profil (mehr), das migriert werden könnte.",
        )

    profile.profile_type = payload.profile_type
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Es existiert bereits ein {_PROFILE_TYPE_LABELS[payload.profile_type]}-Profil - Migration nicht möglich.",
        ) from None
    db.refresh(profile)
    return profile


@router.get("/{profile_type}", response_model=MasterProfileRead)
def get_profile(profile_type: ProfileType, db: Session = Depends(get_db)) -> MasterProfile:
    """Liefert eines der beiden unabhängigen Profile (R1/KTD1)."""
    return _get_profile_or_404(db, profile_type)


@router.put("/{profile_type}", response_model=MasterProfileRead)
def upsert_profile(profile_type: ProfileType, payload: MasterProfileCreate, db: Session = Depends(get_db)) -> MasterProfile:
    """Erstellt das Profil des gegebenen Typs beim ersten Aufruf oder
    überschreibt es vollständig mit den übergebenen Daten (Upsert-Semantik).
    Legt eine neue Zeile an, sofern für diesen `profile_type` noch keine
    existiert - auch wenn bereits eine untypisierte Alt-Zeile
    (`profile_type IS NULL`, Vor-Migrations-Daten) vorhanden ist, kollidiert
    das nicht (die Abfrage filtert explizit auf `profile_type`, nicht auf die
    erste Zeile der Tabelle)."""
    profile = db.query(MasterProfile).filter_by(profile_type=profile_type).first()
    data = payload.model_dump()

    if profile is None:
        profile = MasterProfile(profile_type=profile_type, **data)
        db.add(profile)
    else:
        for field, value in data.items():
            setattr(profile, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Es existiert bereits ein {_PROFILE_TYPE_LABELS[profile_type]}-Profil - bitte erneut versuchen.",
        ) from None
    db.refresh(profile)
    return profile


# Identitätsfelder bleiben exklusiv `PUT /profile/{profile_type}` vorbehalten
# (KTD2) - der CV-Builder darf sie über `PATCH /profile/{profile_type}` nicht
# mitändern, selbst wenn er sie (versehentlich) im Payload mitschickt.
_IDENTITY_FIELDS = {"full_name", "email", "phone", "address", "linkedin", "website", "sender_email"}


@router.patch("/{profile_type}", response_model=MasterProfileRead)
def update_profile_content(
    profile_type: ProfileType, payload: MasterProfileUpdate, db: Session = Depends(get_db)
) -> MasterProfile:
    """Partielles Update der CV-Builder-Inhaltsfelder (R2/R3/R4, KTD2).

    Anders als `PUT /profile/{profile_type}` (Upsert, vollständiges
    Überschreiben) ist dies ein echtes partielles Update: nur die im Payload
    tatsächlich gesetzten Felder werden geändert (`exclude_unset`), fehlende
    Felder bleiben unangetastet. Identitätsfelder (`full_name`, `email`,
    `phone`, `address`, `linkedin`, `website`, `sender_email`)
    bleiben `PUT` vorbehalten und werden hier mit 422 abgelehnt, sofern sie
    überhaupt im Payload gesetzt sind - auch als explizites `null` (siehe
    fix(review): `data.get(field) is not None` hätte ein absichtlich
    gesendetes `{"email": null}` durchgelassen und wäre am NOT-NULL-
    Constraint von `full_name`/`email` mit einem unbehandelten
    IntegrityError statt der dokumentierten 422 gescheitert). `photo_path`
    ist in `MasterProfileUpdate` gar nicht erst enthalten - das schreiben
    ausschließlich die Foto-Endpunkte (`POST`/`DELETE /profile/{profile_type}/photo`).

    Setzt ein bereits existierendes Profil dieses Typs voraus (KTD9): der
    Builder legt kein neues Profil an, das bleibt weiterhin
    `PUT /profile/{profile_type}` vorbehalten.
    """
    data = payload.model_dump(exclude_unset=True)

    identity_violations = [field for field in _IDENTITY_FIELDS if field in data]
    if identity_violations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Identitätsfelder (full_name, email, phone, address, linkedin, website, sender_email) können nicht über "
                f"PATCH /profile/{profile_type} geändert werden: {', '.join(sorted(identity_violations))}. "
                f"Bitte PUT /api/profile/{profile_type} verwenden."
            ),
        )

    profile = _get_profile_or_404(db, profile_type)

    for field, value in data.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


@router.post("/{profile_type}/cv-file", response_model=MasterProfileRead)
def upload_cv_file(
    profile_type: ProfileType,
    file: UploadFile = File(..., description="Lebenslauf als PDF-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Speichert eine Lebenslauf-PDF unverändert (kein KI-Parsing, kein
    Rendering) als Anhang-Datei fürs Profil.

    Anders als `POST /profile/upload-cv` wird diese Datei nicht analysiert,
    um Profilfelder zu befüllen - sie wird 1:1 als E-Mail-Anhang verwendet,
    wenn eine Bewerbung versendet wird (`POST /applications/{id}/send`).
    Ein bereits existierendes Profil dieses Typs ist Voraussetzung, da die
    Datei am Profil hängt.
    """
    profile = _get_profile_or_404(db, profile_type)

    file_bytes = _require_pdf(file)

    cv_path = _cv_file_path_for(profile.id)
    cv_path.parent.mkdir(parents=True, exist_ok=True)
    cv_path.write_bytes(file_bytes)

    profile.cv_file_path = str(cv_path)
    profile.cv_filename = file.filename or "lebenslauf.pdf"
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/{profile_type}/cv-file")
def download_cv_file(profile_type: ProfileType, db: Session = Depends(get_db)) -> StreamingResponse:
    """Liefert die hochgeladene Lebenslauf-Anhang-Datei zurück (z. B. für
    eine Vorschau/Download-Prüfung im Profil-Frontend)."""
    profile = db.query(MasterProfile).filter_by(profile_type=profile_type).first()
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


@router.delete("/{profile_type}/cv-file", response_model=MasterProfileRead)
def delete_cv_file(profile_type: ProfileType, db: Session = Depends(get_db)) -> MasterProfile:
    """Entfernt die hochgeladene Lebenslauf-Anhang-Datei wieder (z. B. um sie
    durch eine andere zu ersetzen)."""
    profile = db.query(MasterProfile).filter_by(profile_type=profile_type).first()
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


@router.post("/{profile_type}/photo", response_model=MasterProfileRead)
def upload_photo(
    profile_type: ProfileType,
    file: UploadFile = File(..., description="Profilfoto als JPEG- oder PNG-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Speichert ein Profilfoto fürs Stammprofil (CV-Builder, R3).

    Ein bereits existierendes Profil dieses Typs ist Voraussetzung, da die
    Datei am Profil hängt. Wechselt das Bildformat gegenüber einem bereits
    vorhandenen Foto (z. B. JPEG -> PNG), wird die alte Datei zuerst entfernt,
    damit keine verwaiste Datei unter der alten Endung zurückbleibt; ein
    Re-Upload im selben Format überschreibt die vorhandene Datei einfach
    (wie bei `cv-file`).
    """
    profile = _get_profile_or_404(db, profile_type)

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


@router.get("/{profile_type}/photo")
def download_photo(profile_type: ProfileType, db: Session = Depends(get_db)) -> StreamingResponse:
    """Liefert das hochgeladene Profilfoto zurück (z. B. für die Vorschau im
    CV-Builder)."""
    profile = db.query(MasterProfile).filter_by(profile_type=profile_type).first()
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


@router.delete("/{profile_type}/photo", response_model=MasterProfileRead)
def delete_photo(profile_type: ProfileType, db: Session = Depends(get_db)) -> MasterProfile:
    """Entfernt das hochgeladene Profilfoto wieder (z. B. um es durch ein
    anderes zu ersetzen)."""
    profile = db.query(MasterProfile).filter_by(profile_type=profile_type).first()
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


@router.post("/{profile_type}/attachments", response_model=MasterProfileRead)
def upload_attachment(
    profile_type: ProfileType,
    file: UploadFile = File(..., description="Zusätzlicher Anhang als PDF-Datei"),
    db: Session = Depends(get_db),
) -> MasterProfile:
    """Fügt dem Profil einen weiteren PDF-Anhang hinzu (z. B. Arbeitszeugnis,
    Zertifikat), der beim Versand einer Bewerbung zusätzlich zum Lebenslauf
    mitgeschickt wird. Auf `MAX_PROFILE_ATTACHMENTS` begrenzt - ein bereits
    existierendes Profil dieses Typs ist Voraussetzung, da die Anhänge am
    Profil hängen."""
    profile = _get_profile_or_404(db, profile_type)

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


@router.get("/{profile_type}/attachments/{attachment_id}")
def download_attachment(
    profile_type: ProfileType, attachment_id: int, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Liefert einen einzelnen zusätzlichen Anhang zurück (z. B. für eine
    Vorschau/Download-Prüfung im Profil-Frontend).

    Prüft zusätzlich, dass der Anhang tatsächlich zum aufgelösten Profil
    dieses `profile_type` gehört (R1/R3) - sonst ließe sich ein Anhang des
    IT-Profils über eine `full_life`-URL abrufen, nur weil dessen
    `attachment_id` bekannt/erraten ist."""
    profile = _get_profile_or_404(db, profile_type)

    attachment = db.get(ProfileAttachment, attachment_id)
    if attachment is None or attachment.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anhang wurde nicht gefunden.")

    attachment_path = Path(attachment.file_path)
    if not attachment_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anhang-Datei wurde nicht gefunden.")

    return StreamingResponse(
        _iter_file(attachment_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{attachment.filename}"'},
    )


@router.delete("/{profile_type}/attachments/{attachment_id}", response_model=MasterProfileRead)
def delete_attachment(profile_type: ProfileType, attachment_id: int, db: Session = Depends(get_db)) -> MasterProfile:
    """Entfernt einen zusätzlichen Anhang wieder (z. B. um Platz für einen
    anderen zu schaffen, da auf MAX_PROFILE_ATTACHMENTS begrenzt).

    Gleiche Ownership-Prüfung wie `download_attachment` oben (R1/R3): ein
    Anhang des IT-Profils lässt sich nicht über eine `full_life`-URL löschen."""
    profile = _get_profile_or_404(db, profile_type)

    attachment = db.get(ProfileAttachment, attachment_id)
    if attachment is None or attachment.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anhang wurde nicht gefunden.")

    attachment_path = Path(attachment.file_path)
    if attachment_path.exists():
        attachment_path.unlink()

    db.delete(attachment)
    db.commit()
    db.refresh(profile)
    return profile
