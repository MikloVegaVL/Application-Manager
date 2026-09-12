---
title: "Stale Docker image and a squatted dev-server port mimic routing/CORS bugs"
date: 2026-09-09
category: developer-experience
module: "dev-environment (docker-compose backend service, Angular dev server)"
problem_type: developer_experience
component: development_workflow
severity: medium
applies_when:
  - "Testing a newly added backend route right after committing, while the backend runs via docker-compose without a source volume mount or --reload"
  - "A route that clearly exists in the checked-out source returns 404 against the running server"
  - "The browser reports a CORS block (no Access-Control-Allow-Origin header) even though the backend would otherwise respond successfully or with an ordinary error status"
  - "Multiple `ng serve` (or any dev-server) processes may be running, so the current session's origin/port may not match a hardcoded single-origin CORS allowlist"
  - "A prior debugging session left a dev server running in the background from an earlier day"
symptoms:
  - "New backend route added in the latest commit returns HTTP 404 even though it is present in source and passes locally under TestClient"
  - "Browser Network tab shows a request as CORS-blocked (missing Access-Control-Allow-Origin) for both the new route and a long-standing, previously-working endpoint"
  - "A request to an existing endpoint returns HTTP 200 in the Network tab but the browser still reports net::ERR_FAILED"
  - "`docker ps -a` shows the backend container's CREATED timestamp predates the commit that added the failing route, despite the container appearing recently \"Up\""
root_cause: config_error
resolution_type: environment_setup
related_components:
  - docker-compose.yml
  - "backend/app/core/config.py (CORS_ORIGINS)"
  - "backend/app/main.py (CORSMiddleware)"
  - "backend/app/db/init_db.py (Alembic migrations on startup)"
tags: [docker, docker-compose, cors, hot-reload, ng-serve, stale-container, dev-environment]
---

# Stale Docker image and a squatted dev-server port mimic routing/CORS bugs

## Context

Commit `1d4a6e5` (`feat(profile): attach up to 3 extra PDF documents to application emails`, `develop`, 2026-09-09) added new backend routes `POST/GET/DELETE /api/profile/attachments[/{id}]`, a new `ProfileAttachment` model, and an Alembic migration (`3cf25349329e_add_profile_attachments_table.py`) for the new `profile_attachments` table.

Testing the new feature in the browser against the already-running local stack produced two misleading symptoms:

- `POST /api/profile/attachments` returned HTTP 404, and the browser additionally reported the request as CORS-blocked (`No 'Access-Control-Allow-Origin' header is present`).
- A follow-up request against the older, pre-existing `/api/profile/cv-file` endpoint failed with `net::ERR_FAILED`, even though the Network tab showed the response had actually landed with HTTP 200.

Both symptoms *read* like defects in the newly shipped code or its CORS setup. Neither was. A local `TestClient` run against the checked-out source returned HTTP 200 for the identical `/api/profile/attachments` request, proving the application code was correct. The actual causes were two independent, compounding operational conditions in the local dev environment, and the fix required zero code changes.

## Guidance

When a route that demonstrably exists in source 404s against a "locally running" server, or a request looks CORS-blocked despite the Network tab showing a real HTTP response, check the environment before assuming an application-code bug:

**1. Is the running backend container actually built from current source?**

```bash
docker ps -a
```

Compare the `backend` container's `CREATED` timestamp against the date of the last relevant commit. `CREATED` is Docker Engine's own timestamp for when the container was made from an image — per Docker's documented behavior it is untouched by `restart`/`Up X minutes`, so a container can show a recent uptime while still running code from an image built long before your latest commit. If `CREATED` predates the commit, the running server cannot possibly have the new routes.

Confirm directly by diffing the *running* server's route table against source:

```bash
curl -s http://localhost:8000/openapi.json | python3 -c "
import json, sys
paths = json.load(sys.stdin)['paths']
for p in sorted(paths):
    print(p)
"
```

If the new endpoint's path is absent from this list, the container is stale — the routes exist in source but were never baked into the image the server is actually running.

Fix: rebuild and recreate the container from current source.

```bash
docker compose up --build -d backend
```

**2. Does the dev frontend's actual origin match the backend's CORS allowlist?**

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -i node
ps aux | grep "ng serve"
```

Look for more than one `ng serve`/dev-server process, and note which port each is actually bound to. Per the Angular CLI's documented dev-server behavior, it silently falls back to a random free port when its default port is already occupied by a stale process from an earlier session — it does not warn loudly or refuse to start. If the backend's CORS allowlist only trusts one hardcoded origin/port, a dev server that fell back to a different port will never get `Access-Control-Allow-Origin` in its responses, and the browser reports *any* response from that origin — 200, 404, or 500 — as CORS-blocked / `net::ERR_FAILED`, regardless of what the server actually returned.

Fix: kill the stale process squatting on the expected port, then restart the frontend so it binds to the port the backend allowlist actually trusts.

```bash
kill <stale ng-serve PID>
npm start   # re-run from frontend/, binds to :4200
```

Verify the fix directly by confirming the CORS header appears for a request with the expected Origin header:

```bash
curl -s -o /dev/null -D - -X POST http://localhost:8000/api/profile/cv-file \
  -H "Origin: http://localhost:4200" ... | grep -i access-control-allow-origin
```

Check both conditions — they compound. A stale container can make a route genuinely 404, and a mismatched dev-server origin can make that same 404 (or any other response) look like a CORS failure on top of it, hiding the real status entirely.

## Why This Matters

**Stale image, no hot reload (mechanism).** `docker-compose.yml`'s `backend` service builds the FastAPI image from source (`build: context: ./backend, dockerfile: Dockerfile`) and only mounts `./backend/generated:/app/generated` as a volume — the application source itself is never volume-mounted into the container. The Dockerfile does `COPY . .` at build time, baking the source into the image, and its `CMD` runs `uvicorn app.main:app --host 0.0.0.0 --port 8000` without `--reload`. The consequence: once the container is created, editing or committing source on the host has zero effect on the running process until the image is explicitly rebuilt and the container recreated — a plain `docker compose restart`, or an already-`Up` container, is not enough, no matter how recently it "started."

Rebuilding is safe here specifically because of how state is separated: Postgres data lives in the independent `pgdata` named volume, which a `backend`-only rebuild never touches, and `backend/app/main.py`'s `lifespan` hook calls `init_db()` (`backend/app/db/init_db.py`) on every startup. For a non-SQLite `DATABASE_URL` (the Postgres URL docker-compose sets for the `backend` service), `init_db()` runs real Alembic migrations (`alembic upgrade head`) rather than `Base.metadata.create_all()` — the module's own docstring explicitly documents that `create_all()` cannot retrofit already-existing tables with new columns, which is why the project moved to real migrations. So any new migration shipped with a feature (here, `3cf25349329e_add_profile_attachments_table.py`, creating `profile_attachments`) is applied automatically the moment the rebuilt container starts — there is no separate manual migration step to remember or forget.

**Hardcoded single-origin CORS allowlist + silent port fallback (mechanism).** `backend/app/core/config.py` defines `CORS_ORIGINS: list[str] = ["http://localhost:4200"]` as a hardcoded default, and `backend/.env.example` has no `CORS_ORIGINS` entry to override it — so unless a developer's own untracked `.env` sets it, exactly one origin is ever trusted. `backend/app/main.py` wires this straight into Starlette's `CORSMiddleware` via `allow_origins=settings.CORS_ORIGINS`. `CORSMiddleware` decides whether to attach `Access-Control-Allow-Origin` purely by matching the request's `Origin` header against this allowlist — independent of the response's actual HTTP status code (verified by reading Starlette's `CORSMiddleware.send`/`simple_response` implementation). A request from an untrusted origin gets no CORS header regardless of whether the underlying handler would have returned 200, 404, or 500. The browser then suppresses the response body/status entirely from the calling page and surfaces it as a CORS failure (`net::ERR_FAILED` / "No 'Access-Control-Allow-Origin' header is present") — masking whatever the server actually did.

Compounding this, `frontend/src/environments/environment.development.ts` hardcodes `apiBaseUrl: 'http://localhost:8000/api'` with no dev-server proxy layer, so the Angular dev server always calls the backend directly using whatever port it happens to be bound to as its `Origin`. Angular's CLI dev server does not fail or warn loudly when its default port (4200) is occupied — it silently binds to the next free port instead. A stale `ng serve` process left running from a prior session is enough to push a brand-new dev session onto a different port that the hardcoded allowlist has never heard of.

Net effect: two entirely separate, low-visibility environment conditions each independently produce a symptom that looks exactly like an application bug in the newly shipped feature, when the feature's code was correct in both cases.

## When to Apply

- After pulling or committing new backend code while `docker compose` services from a previous session are already running (container shows `Up X minutes/hours` but was never rebuilt).
- When the browser reports a CORS block (`net::ERR_FAILED`, missing `Access-Control-Allow-Origin`) on an endpoint that a local `TestClient` run or unit/integration test confirms works correctly against the same source.
- When `ng serve` / `npm start` binds to a port other than `:4200` (or whatever the backend's `CORS_ORIGINS` allowlist trusts).
- Before concluding a newly added route is "not registered" or "misconfigured" purely from a 404 in the browser — verify against the running server's actual `openapi.json`, not just the source tree.
- Any time a new commit lands during a long-running local dev session and something that should work suddenly acts like it doesn't.

## Examples

Check container staleness vs. the last relevant commit:

```bash
docker ps -a
# compare backend's CREATED timestamp to: git log -1 --format=%ci <commit>
```

Diff the running server's actual route table against source:

```bash
curl -s http://localhost:8000/openapi.json | python3 -c "
import json, sys
paths = json.load(sys.stdin)['paths']
for p in sorted(paths):
    print(p)
"
```

Find concurrent dev-server processes and which port each actually owns:

```bash
lsof -nP -iTCP -sTCP:LISTEN
ps aux | grep "ng serve"
```

Rebuild the backend image and recreate the container from current source (safe — Postgres data is in the separate `pgdata` volume, and Alembic migrations run automatically on the new container's first startup):

```bash
docker compose up --build -d backend
```

Free the squatted port and restart the frontend so it binds where the backend's CORS allowlist expects it:

```bash
kill <stale ng-serve PID>
npm start   # from frontend/ - plain `ng serve`, binds to :4200
```

Verify the CORS fix directly:

```bash
curl -s -o /dev/null -D - -X POST http://localhost:8000/api/profile/cv-file \
  -H "Origin: http://localhost:4200" | grep -i access-control-allow-origin
# expect: access-control-allow-origin: http://localhost:4200
```

## Related

- No existing `docs/solutions/` entries cover this problem area (checked `docs/solutions/integration-issues/`, `docs/solutions/performance-issues/`, `docs/solutions/test-failures/` — all low overlap; closest is `docs/solutions/performance-issues/ollama-concurrent-model-residency-memory-pressure.md`, which shares Docker/container awareness but is about Ollama model memory, not stale images or CORS).
- See also (added 2026-09-12): [Rebasing an Alembic migration onto a sibling branch silently strands already-migrated databases](../database-issues/alembic-migration-rebase-silently-skips-sibling-branch.md) — a later investigation in the same problem area found a second, distinct defect underneath this one: even rebuilding the stale container described above would not have been enough, because a migration-graph topology bug independently meant the rebuilt container's database would never receive one migration branch's DDL.
