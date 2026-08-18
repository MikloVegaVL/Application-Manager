---
title: "FastAPI TestClient + in-memory SQLite: StaticPool and lifespan isolation pitfalls"
date: 2026-08-15
category: test-failures
module: "backend/tests/api (job search API test suite)"
problem_type: test_failure
component: testing_framework
symptoms:
  - "sqlalchemy.exc.OperationalError: no such table raised mid-test even though Base.metadata.create_all(bind=engine) had already run"
  - A real file-backed app.db was created/touched in the repo during test runs, polluting real application state
  - TestClient(app) used with a `with` statement triggered FastAPI's real lifespan startup, calling init_db() against the production-default DATABASE_URL instead of the test's isolated in-memory engine
root_cause: test_isolation
resolution_type: test_fix
severity: medium
related_components: [database, development_workflow]
tags: [fastapi, testclient, sqlite, staticpool, lifespan, pytest, dependency-override, connection-pooling]
---

# FastAPI TestClient + in-memory SQLite: StaticPool and lifespan isolation pitfalls

## Problem

Writing `backend/tests/api/test_jobs.py` — new integration tests hitting `/api/jobs/*` via `fastapi.testclient.TestClient` — surfaced two related test-infrastructure bugs in the same debugging pass: an in-memory SQLite test engine that lost its tables between requests, and a `TestClient(app)` usage pattern that silently ran the real app startup against the real on-disk database.

## Symptoms

- `sqlite3.OperationalError: no such table: ...` (surfaced as SQLAlchemy's `OperationalError`) raised on the first HTTP request made through `TestClient`, even though `Base.metadata.create_all(bind=engine)` had just been called against the same `engine` object moments earlier in the same test.
- No test failure at all for the second bug — the suite passed green. The only symptom was an unexpected `app.db` file (a generated, untracked SQLite file — not part of the repo's tracked source) showing up as new in `backend/` (`git status` diff) after running the test suite, meaning tests had written to the real application database instead of staying isolated.

## What Didn't Work

Both bugs were diagnosed fairly directly rather than through failed fix attempts:

- Bug 1 (`no such table`) was diagnosed from the exception together with checking how SQLAlchemy actually pools `sqlite:///:memory:` connections against its source — the first hypothesis (a pool that hands out a fresh connection per checkout) turned out to be wrong; see **Why This Works** below for the real mechanism.
- Bug 2 had no exception to go on at all — the tests were green. It was only caught by noticing the unexpected `app.db` file (generated, untracked) appearing in `backend/` after a test run. Tracing that back led to `backend/app/main.py`'s `lifespan` (`backend/app/main.py:17-20`), which calls `init_db()` unconditionally on startup, and to the realization that the test fixture's original `with TestClient(app) as client:` form triggers that startup event even when `get_db` is already overridden — because the override only affects the DB dependency used inside request handlers, not the lifespan hook, which runs before any override is consulted.

## Solution

Both fixes now live together in the `client()` fixture in `backend/tests/api/test_jobs.py:23-47`.

**Fix 1 — pin the in-memory SQLite engine to a single connection with `StaticPool`:**

```python
# Before
from sqlalchemy import create_engine

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
```

```python
# After (backend/tests/api/test_jobs.py:12,14,28-32)
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

**Fix 2 — construct `TestClient(app)` without the `with` statement, so lifespan startup/shutdown never fire:**

```python
# Before (the idiomatic FastAPI testing pattern)
app.dependency_overrides[get_db] = _override_get_db
with TestClient(app) as client:
    yield client
app.dependency_overrides.clear()
```

```python
# After (backend/tests/api/test_jobs.py:43-47)
app.dependency_overrides[get_db] = _override_get_db
try:
    yield TestClient(app)
finally:
    app.dependency_overrides.clear()
```

The file's own docstring (`backend/tests/api/test_jobs.py:1-7`) records the same rationale: use an isolated in-memory engine instead of the app's lifespan `init_db()`, specifically so tests don't create a real `app.db` file in the repo.

## Why This Works

**Bug 1 — SQLAlchemy's default `sqlite:///:memory:` pool is per-thread, and `TestClient` runs the app on a different thread than the fixture.** This is a property of SQLAlchemy and Starlette themselves — installed third-party dependencies, not part of this repo's own tracked source (verified against the installed packages under `backend/venv/`). SQLAlchemy's SQLite dialect does not hand a non-file URL like `:memory:` to its general-purpose pool; it detects that the URL isn't file-backed and returns `SingletonThreadPool` instead (see the `get_pool_class` classmethod in SQLAlchemy's SQLite pysqlite dialect module), which "maintains one connection per thread, never moving a connection to a thread other than the one which it was created in" (per the `SingletonThreadPool` docstring in SQLAlchemy's pool implementation module). *Within* a single thread, `SingletonThreadPool` reuses the same connection for every checkout — so the bug isn't about connections churning per-checkout. It's about **which thread** does the checking out: `Base.metadata.create_all(bind=engine)` (`backend/tests/api/test_jobs.py:34`) runs on the test/fixture's own thread, but `TestClient` dispatches actual HTTP requests to the ASGI app through an `anyio` blocking portal running on a separate worker thread (Starlette's `testclient.py`, `TestClient.__enter__`). Because `SingletonThreadPool` keys its one connection by thread identity, the request-handling thread's `get_db` checkout (`backend/tests/api/test_jobs.py:36-41`) gets its *own*, separate `:memory:` connection — one that never saw `create_all()`, hence "no such table." `StaticPool` (`backend/tests/api/test_jobs.py:14` and `:31`) fixes this by collapsing to a single connection *regardless of which thread checks it out*, so the tables created on the fixture's thread are visible to the request-handling thread too.

**Bug 2 — entering `TestClient` as a context manager runs the real FastAPI lifespan.** FastAPI/Starlette's `TestClient.__enter__` runs the app's startup lifespan handlers before yielding. This app's `lifespan` (`backend/app/main.py:17-20`) unconditionally calls `init_db()` on startup. `init_db()` is not routed through the `get_db` FastAPI dependency the test overrides at `backend/tests/api/test_jobs.py:43` — it operates directly against whatever `settings.DATABASE_URL` resolves to, which defaults to `sqlite:///./app.db` (`backend/app/core/config.py:30`), a real file-backed SQLite database in the repo's working tree. Overriding `get_db` isolates request-handling code paths from the real DB, but it does nothing to the lifespan hook, since the hook runs independently of any per-request dependency resolution and fires the moment the context manager is entered — before the override even matters. Not entering the context manager (`yield TestClient(app)` instead of `with TestClient(app) as client:`) means `__enter__`/`__exit__` are never called, so `lifespan` — and therefore `init_db()` — never runs during the test, and the `get_db` override remains the only thing tests rely on for DB access.

## Prevention

- Any test SQLAlchemy `engine` built against `sqlite:///:memory:` that will be used through a `TestClient`-driven request — or any other code path that runs on a different thread than the one that created the engine and ran `create_all()` — must pass `poolclass=StaticPool`. SQLAlchemy's own default for `sqlite:///:memory:` is `SingletonThreadPool` (one connection per thread), which is already safe for repeated checkouts *within* the same thread, but breaks the moment a different thread — such as `TestClient`'s ASGI worker thread — tries to check out a connection of its own. There's no benefit to omitting `StaticPool` even when this doesn't (yet) bite — treat it as mandatory boilerplate for any `sqlite:///:memory:` engine driven through `TestClient` in this repo, not an optional tuning knob.
- Before reaching for `with TestClient(app) as client:` in this codebase, check whether `app`'s `lifespan` (`backend/app/main.py:17-20`) touches state that a dependency override cannot reach — here, `init_db()` writes directly against `settings.DATABASE_URL` rather than going through `get_db`. If it does, either:
  - Skip the context-manager form entirely (`TestClient(app)` without `with`), relying solely on `app.dependency_overrides` for isolation, as done in `backend/tests/api/test_jobs.py:43-47`, or
  - Make the lifespan itself override-aware (e.g. have `init_db()` accept/resolve an injectable engine/session rather than reading `settings.DATABASE_URL` directly), so that using `with TestClient(app)` becomes safe by construction.
- When a test suite passes but an unexpected file (like `app.db`) shows up in `git status` afterward, treat that as a real signal of state leakage, not noise — it was the only observable symptom of Bug 2 here. Any `*.db` output under `backend/`, including this `app.db` file, is not currently listed in the repo's `.gitignore`; adding it would be a low-cost safety net so a lifespan regression like this produces a visible diff instead of silently poisoning committed state.
- New FastAPI route test files added under `backend/tests/api/` should copy the `client()` fixture pattern from `backend/tests/api/test_jobs.py:23-47` wholesale (isolated `StaticPool` in-memory engine + `get_db` override + non-context-manager `TestClient`) rather than re-deriving it, to avoid reintroducing either bug.

## Related Issues

None found. `docs/solutions/` had no prior entries at the time this doc was written, and a GitHub issue search (`gh issue list --search "sqlite testclient lifespan" --state all`) returned no matches.
