"""Generische Datei-Validierungs-/Streaming-Hilfsfunktionen, gemeinsam
genutzt von mehreren Routern (`app.api.profile`, `app.api.cv_builder`) -
nicht profil- oder CV-Builder-spezifisch."""
from pathlib import Path

from fastapi import HTTPException, UploadFile, status


def _require_pdf(file: UploadFile) -> bytes:
    """Gemeinsame Validierung für alle PDF-Uploads dieses Routers: nur PDF,
    nicht leer. Wirft `HTTPException` bei Verstoß, sonst die gelesenen Bytes."""
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
    return file_bytes


# --- Zusätzliche Anhänge (PDF/JPEG/PNG/DOC/DOCX) -------------------------
#
# Die zusätzlichen Profil-Anhänge (`app.api.profile`) dürfen neben PDF auch
# Bilder (JPEG/PNG) und Word-Dokumente (DOC/DOCX) enthalten. Anders als der
# Lebenslauf (`_require_pdf`, strikt PDF) werden diese Dateien 1:1 als weitere
# E-Mail-Anhänge mitgeschickt und müssen deshalb mit ihrem echten Media-Type
# (nicht pauschal `application/pdf`) gespeichert und ausgeliefert werden.

# Dateiendung -> Media-Type. Die Endung ist zugleich die Speicher-Endung
# (`jpeg` wird zu `jpg` normalisiert, siehe `_ATTACHMENT_EXT_NORMALIZE`).
ATTACHMENT_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Media-Type -> kanonische Dateiendung (Fallback, wenn der Dateiname keine
# erkennbare Endung hat - dann entscheidet der Client-Content-Type).
_ATTACHMENT_MEDIA_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# jpeg/jpg sind beide JPEG - zur Speicherung auf eine Endung normalisieren.
_ATTACHMENT_EXT_NORMALIZE: dict[str, str] = {"jpeg": "jpg"}


def _require_attachment_file(file: UploadFile) -> tuple[bytes, str, str]:
    """Validierung für zusätzliche Profil-Anhänge (PDF/JPEG/PNG/DOC/DOCX):
    nicht leer, Dateityp über Dateiendung ODER Client-Content-Type bestimmt
    (analog `_require_pdf`, das ebenfalls Endung-oder-Content-Type prüft).
    Wirft `HTTPException` (415) bei nicht unterstütztem Typ bzw. (400) bei
    leerer Datei; sonst `(Bytes, Speicher-Endung, Media-Type)`."""
    filename = (file.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    content_type = (file.content_type or "").lower()

    if ext in ATTACHMENT_MEDIA_TYPES:
        media_type = ATTACHMENT_MEDIA_TYPES[ext]
    elif content_type in _ATTACHMENT_MEDIA_TO_EXT:
        ext = _ATTACHMENT_MEDIA_TO_EXT[content_type]
        media_type = content_type
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Nur PDF-, JPG-, PNG-, DOC- oder DOCX-Dateien werden unterstützt.",
        )

    ext = _ATTACHMENT_EXT_NORMALIZE.get(ext, ext)

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die hochgeladene Datei ist leer.",
        )
    return file_bytes, ext, media_type


def _iter_file(path: Path, chunk_size: int = 65_536):
    """Streamt eine Datei chunkweise (gemeinsam genutzt von den
    `cv-file`- und `attachments`-Download-Routen)."""
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk
