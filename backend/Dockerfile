# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- Systemabhängigkeiten für WeasyPrint (HTML/CSS -> PDF) ---
# Pango/Cairo/GDK-Pixbuf übernehmen das eigentliche Rendering, libffi-dev und
# shared-mime-info werden von WeasyPrints Pipeline benötigt, die beiden
# fonts-Pakete liefern brauchbare Standard-Schriftarten für die PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-liberation \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# --- Python-Abhängigkeiten ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Playwright-Chromium inkl. benötigter Betriebssystem-Bibliotheken ---
# (für den generischen Fallback-Web-Scraper in app/services/job_search_service.py)
RUN playwright install --with-deps chromium

# --- Anwendungscode ---
COPY . .

# Zielverzeichnis für generierte Bewerbungs-PDFs (siehe GENERATED_FILES_DIR
# in app/core/config.py) - wird zusätzlich per Volume in docker-compose.yml
# persistiert.
RUN mkdir -p /app/generated/applications

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
