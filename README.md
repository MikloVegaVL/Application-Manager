# 🚀 Application-Manager (Personal AI Application Assistant)

Personal, AI-powered web application for job searching and for creating and
automatically filling in job applications (cover letter & CV). It searches job
offers, matches them against your master profile and generates tailored
application documents including PDF generation and email delivery.

---

## 🛠️ Tech Stack

- **Frontend:** Angular 17+ (standalone components, signals), Angular Material, Nginx
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy v2, Pydantic v2
- **Database:** PostgreSQL (Docker/production), SQLite (local dev fallback without Docker)
- **AI & documents:** Ollama (locally hosted LLM), Playwright, WeasyPrint, pypdf
- **Containerization:** Docker & Docker Compose

- `/backend` - FastAPI application
- `/frontend` - Angular application

---

## ⚡ Quick start with Docker Compose (recommended)

Starts the frontend, backend and PostgreSQL with a single command.

**Prerequisite:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (including Docker Compose).

```bash
# 1. Create the backend environment variables (required for SMTP features; the
#    Ollama variables (OLLAMA_BASE_URL/OLLAMA_MODEL) already have sensible
#    defaults for Docker Compose - without this step the app still starts,
#    only mail features will return a clear configuration error instead of
#    working)
cp backend/.env.example backend/.env
# ... and fill in SMTP_* with real values (no API key needed for the AI -
# Ollama runs as its own Docker Compose service)

# 2. (optional) Override the Postgres credentials
cp .env.example .env

# 3. Start
docker-compose up --build
```

Reachable afterwards at:

| Service  | URL                          |
| -------- | ----------------------------- |
| Frontend | http://localhost:8080         |
| Backend (API + Swagger docs) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 (referenced only inside the container as `db`) |

The frontend serves `/api/*` requests internally through an Nginx reverse proxy
to the backend (see `frontend/nginx.conf`) - this avoids CORS issues in
container operation. Generated application PDFs are persisted to
`backend/generated/` via a volume.

Stop with `docker-compose down` (the database volume is kept), or
`docker-compose down -v` to also delete the Postgres data.

---

## 🧑‍💻 Local development without Docker

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in with real values
uvicorn app.main:app --reload
```

Uses a local SQLite file by default (`DATABASE_URL` unconfigured).

**System requirement (macOS):** PDF generation uses WeasyPrint, which needs
native libraries (Pango, Cairo, GDK-Pixbuf, GLib) that are not installed via
pip:

```bash
brew install pango
```

(Pango automatically pulls in Cairo/GDK-Pixbuf/GLib as dependencies.)

### Frontend

```bash
cd frontend
npm install
npm start   # http://localhost:4200, expects the backend at http://localhost:8000
```
