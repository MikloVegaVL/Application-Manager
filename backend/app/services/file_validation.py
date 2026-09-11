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


def _iter_file(path: Path, chunk_size: int = 65_536):
    """Streamt eine Datei chunkweise (gemeinsam genutzt von den
    `cv-file`- und `attachments`-Download-Routen)."""
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk
