# 🚀 Application-Manager (Personal AI Application Assistant)

Persönliche, KI-gestützte Web-Anwendung zur Jobsuche sowie zur Erstellung
und zum automatischen Befüllen von Bewerbungen (Anschreiben & Lebenslauf).
Sie sucht Stellenangebote, gleicht sie mit deinem Master-Profil ab und
generiert maßgeschneiderte Bewerbungsunterlagen inkl. PDF-Erzeugung und
E-Mail-Versand.

---

## 🛠️ Tech Stack

- **Frontend:** Angular 17+ (Standalone Components, Signals), Angular Material, Nginx
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy v2, Pydantic v2
- **Datenbank:** PostgreSQL (Docker/Produktion), SQLite (lokaler Dev-Fallback ohne Docker)
- **KI & Dokumente:** OpenAI API (GPT-4o), Playwright, WeasyPrint, pypdf
- **Containerisierung:** Docker & Docker Compose

- `/backend` - FastAPI-Anwendung
- `/frontend` - Angular-Anwendung

---

## ⚡ Schnellstart mit Docker Compose (empfohlen)

Startet Frontend, Backend und PostgreSQL mit einem Befehl.

**Voraussetzung:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (inkl. Docker Compose).

```bash
# 1. Backend-Umgebungsvariablen anlegen (für OpenAI/SMTP-Funktionen nötig,
#    ohne diesen Schritt startet die App trotzdem - nur KI/Mail-Features
#    liefern dann einen klaren Konfigurationsfehler statt zu funktionieren)
cp backend/.env.example backend/.env
# ... und darin OPENAI_API_KEY / SMTP_* mit echten Werten befüllen

# 2. (optional) Postgres-Zugangsdaten überschreiben
cp .env.example .env

# 3. Starten
docker-compose up --build
```

Danach erreichbar unter:

| Service  | URL                          |
| -------- | ----------------------------- |
| Frontend | http://localhost:8080         |
| Backend (API + Swagger-Docs) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 (nur containerintern als `db` referenziert) |

Das Frontend liefert `/api/*`-Anfragen intern über einen Nginx-Reverse-Proxy
an das Backend aus (siehe `frontend/nginx.conf`) - dadurch treten im
Container-Betrieb keine CORS-Probleme auf. Generierte Bewerbungs-PDFs werden
per Volume nach `backend/generated/` persistiert.

Stoppen mit `docker-compose down` (Datenbank-Volume bleibt erhalten), bzw.
`docker-compose down -v`, um auch die Postgres-Daten zu löschen.

---

## 🧑‍💻 Lokale Entwicklung ohne Docker

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # danach mit echten Werten befüllen
uvicorn app.main:app --reload
```

Nutzt standardmäßig eine lokale SQLite-Datei (`DATABASE_URL` unkonfiguriert).

**Systemvoraussetzung (macOS):** Die PDF-Erzeugung nutzt WeasyPrint, das
native Libraries (Pango, Cairo, GDK-Pixbuf, GLib) benötigt, die nicht über
pip installiert werden:

```bash
brew install pango
```

(Pango zieht Cairo/GDK-Pixbuf/GLib automatisch als Abhängigkeiten mit.)

### Frontend

```bash
cd frontend
npm install
npm start   # http://localhost:4200, erwartet Backend auf http://localhost:8000
```
