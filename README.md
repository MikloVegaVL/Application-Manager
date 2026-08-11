# Application-Manager

Persönliche Web-Anwendung zur Jobsuche sowie zur Erstellung und zum
automatischen Befüllen von Bewerbungen (Anschreiben & Lebenslauf) inkl.
PDF-Generierung und E-Mail-Versand.

- `/backend` - FastAPI (Python 3.11+), SQLAlchemy v2, Pydantic v2
- `/frontend` - Angular 17+ (Standalone Components, Signals), Angular Material

## Backend-Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # danach mit echten Werten befüllen
uvicorn app.main:app --reload
```

**Systemvoraussetzung (macOS):** Die PDF-Erzeugung nutzt WeasyPrint, das
native Libraries (Pango, Cairo, GDK-Pixbuf, GLib) benötigt, die nicht über
pip installiert werden:

```bash
brew install pango
```

(Pango zieht Cairo/GDK-Pixbuf/GLib automatisch als Abhängigkeiten mit.)

## Frontend-Setup

```bash
cd frontend
npm install
npm start   # http://localhost:4200, erwartet Backend auf http://localhost:8000
```
