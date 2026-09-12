---
title: "Rebasing an Alembic migration onto a sibling branch silently strands already-migrated databases"
date: 2026-09-12
category: database-issues
module: backend-alembic-migrations
problem_type: database_issue
component: database
symptoms:
  - "alembic upgrade head reports success but emits zero DDL and leaves the schema unchanged on a database already stamped at the sibling branch revision"
  - "two Alembic migrations independently branch off the same parent revision, producing two heads"
  - "a round-trip test's downgrade(cfg, \"-1\") fails or is ambiguous because a two-parent merge point has no single \"one step back\""
  - "an API response silently omits columns from the sibling branch even though alembic current reports the database is up to date"
root_cause: logic_error
resolution_type: migration
severity: high
related_components:
  - testing_framework
  - backend_api
tags:
  - alembic
  - migrations
  - database-migration-graph
  - merge-revision
  - postgres
  - down-revision
  - silent-failure
---

# Rebasing an Alembic migration onto a sibling branch silently strands already-migrated databases

## Problem

Two Alembic migrations — `17c15ce91b4e` ("add cv builder fields") and `7b2f5c9d1a34` ("add sent_to_email to applications") — were created independently, each with `down_revision = '3cf25349329e'`, producing two heads. A fix attempted to resolve that graph split by rebasing `7b2f5c9d1a34`'s `down_revision` onto `17c15ce91b4e` instead of creating a proper merge revision. That silently broke `alembic upgrade head` for any database that had already applied `7b2f5c9d1a34` under the original two-head graph.

## Symptoms

- Against a Postgres database whose `alembic_version` was stamped at `7b2f5c9d1a34` (applied back when that revision was itself a head), `alembic upgrade head` exits 0 with no `"Running upgrade ..."` log lines and no schema change — the command reports success but silently does nothing.
- A before/after `\d master_profiles` schema diff on that database showed zero difference after running `alembic upgrade head`, even though `17c15ce91b4e`'s columns (`photo_path`, `photo_filename`, `languages_json`, `projects_json`, `template_id`) were still missing.
- Application code depending on those columns fails at query time (undefined/no-such-column error), or — if a stale application binary/response model is also involved — silently omits the affected fields from its API response (e.g. `GET /profile` missing `languages_json`, `photo_filename`, etc.) instead of erroring.
- `alembic current` reports a revision that Alembic's own graph now treats as equal to (or a descendant of) `head`, even though a sibling branch's DDL was never applied to that database.
- A round-trip test (`test_migration_upgrade_downgrade_upgrade_round_trips`) fails or becomes ambiguous when its `downgrade(alembic_cfg, "-1")` call is run against a graph where `head` is a two-parent merge point, since "one step back" from a merge point is not well-defined.

## What Didn't Work

The migration graph split (`17c15ce91b4e` and `7b2f5c9d1a34` both parented on `3cf25349329e`) was originally causing an unrelated test failure: `downgrade(alembic_cfg, "-1")` was ambiguous, because Alembic can't tell which of two heads "-1" means one step back from.

The attempted fix was to eliminate the second head by rewriting history: pointing `7b2f5c9d1a34`'s `down_revision` directly at `17c15ce91b4e`, turning the branch into a straight line so only one head remained and `-1` became unambiguous again.

This broke any database that had already run `alembic upgrade head` under the original two-head graph and ended up stamped at `7b2f5c9d1a34`. After the rebase, Alembic's graph considers `7b2f5c9d1a34` a descendant of `17c15ce91b4e` (or the head itself) — so a database already stamped there looks, from Alembic's perspective, like it's already at (or past) the head. `alembic upgrade head` has no mechanism to notice that the *history* underneath that stamp changed; it only compares the stamped revision against the current head pointer, sees no gap, and does nothing. This was reproduced live against a real docker-compose Postgres database: `alembic current` showed `7b2f5c9d1a34`, and `alembic upgrade head` produced zero DDL output and left the schema completely unchanged.

Rebasing a `down_revision` fixes the *test's* view of the graph (single head, unambiguous `-1`) but silently strands every already-migrated database, because it changes the meaning of a revision ID that a real database is already stamped with, rather than adding a new node that both branches walk through.

## Solution

1. Reverted `7b2f5c9d1a34`'s `down_revision` back to its original, correct parent:

```python
# backend/alembic/versions/7b2f5c9d1a34_add_sent_to_email_to_applications.py:14-18
revision: str = '7b2f5c9d1a34'
# Branches independently off 3cf25349329e, same as 17c15ce91b4e - do NOT
# rebase this onto 17c15ce91b4e; a real merge revision (d98463c22408) joins
# them instead. See that file for why (ce-debug, 2026-09-12).
down_revision: str | None = '3cf25349329e'
```

2. Generated a proper Alembic merge revision joining the two heads (`alembic merge -m "..." 17c15ce91b4e 7b2f5c9d1a34`), which produced a no-op node with both parents as `down_revision`:

```python
# backend/alembic/versions/d98463c22408_merge_cv_builder_and_sent_to_email_heads.py:27-38
revision: str = 'd98463c22408'
down_revision: str | None = ('17c15ce91b4e', '7b2f5c9d1a34')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

3. Retargeted the test that motivated the original (incorrect) rebase away from the now-ambiguous `-1` and onto the explicit shared-parent boundary, since the test's actual intent was only to check `17c15ce91b4e`'s own upgrade/downgrade round trip:

```python
# backend/tests/services/test_master_profile_schema.py:179-183
upgrade(alembic_cfg, "head")
# Explizites Ziel statt `downgrade(cfg, "-1")`: "head" ist ein Merge-Punkt
# (siehe `d98463c22408`), von dort ist "ein Schritt zurück" mehrdeutig.
downgrade(alembic_cfg, "3cf25349329e")
upgrade(alembic_cfg, "head")
```

4. Added a regression test that stamps a fresh database at only the `7b2f5c9d1a34` branch (mirroring a database migrated under the old two-head graph before the merge revision existed), then asserts `alembic upgrade head` correctly picks up the sibling branch's DDL (`backend/tests/services/test_master_profile_schema.py:212-234`, `test_merge_revision_heals_a_database_stuck_on_only_the_sent_to_email_branch`).

Verification: against a disposable copy of the live Postgres database (schema-only `pg_dump` plus manually re-inserting the stamped `alembic_version` row), `alembic upgrade head` now printed `"Running upgrade 3cf25349329e -> 17c15ce91b4e"` before reaching the merge point — a line that was entirely absent under the rebased graph. The fix was then applied to the real database, and a live `GET /profile` response confirmed the previously-missing fields (`photo_filename`, `languages_json`, `projects_json`, `template_id` — `photo_path` is a database column but is deliberately never part of the API response) were present, along with the `skills_json` flat-string-to-leveled-entry backfill from `17c15ce91b4e`'s `upgrade()`.

This fix is opened in PR #11 (https://github.com/MikloVegaVL/Application-Manager/pull/11), unmerged as of this writing.

## Why This Works

Alembic determines what to run by walking the DAG of revisions from a database's stamped `alembic_version` row(s) to the target (`head`), applying every `upgrade()` on nodes along that path that the database hasn't already passed through. A merge revision is a real node in that graph: it has two parents (`down_revision = ('17c15ce91b4e', '7b2f5c9d1a34')`), so reaching it from either parent alone is an incomplete path. A database stamped at `7b2f5c9d1a34` is missing the `17c15ce91b4e` half of that path, and Alembic's graph-walk logic detects exactly that gap — it finds the shortest route from the stamped revision to the merge point, discovers it must also pass through the sibling branch, and applies `17c15ce91b4e`'s `upgrade()` before recording the merge revision as reached. This is the mechanism that produced the `"Running upgrade 3cf25349329e -> 17c15ce91b4e"` line during verification.

Rebasing, by contrast, doesn't add a node — it mutates an existing node's parent pointer, changing what "being at revision `7b2f5c9d1a34`" means in the graph without changing the identifier a database uses to record that it's there. `alembic upgrade head` only ever asks "is the stamped revision equal to, or an ancestor of, the current head?" — it does not compare *how* an already-stamped revision fits into history before and after a change. After the rebase, `7b2f5c9d1a34` reads as at-or-past head, so the answer is "nothing to do," even though the actual column-adding code in `17c15ce91b4e` was never executed against that database. The merge revision's two-parent structure is precisely the data Alembic needs to notice the missing branch; a rebased single parent pointer erases that data instead of encoding it.

## Prevention

- Before changing the `down_revision` of any migration that has already been merged/pushed (as opposed to one still only on your own unpushed branch), ask: could any database — including a local docker-compose one, staging, or production — already be stamped at that revision or one of its descendants under the *current* graph? If yes, changing `down_revision` risks stranding that database exactly as happened here.
- When two migrations are independently created branching off the same parent (a near-inevitable outcome of parallel feature branches touching the schema), the correct tool to join them is always `alembic merge <rev1> <rev2>`, never rewriting one revision's `down_revision` to point at the other. A merge revision adds a graph node that Alembic can route through; a rebase silently redefines an existing one.
- When a test's failure traces back to an ambiguous relative target (e.g. `downgrade(cfg, "-1")` at a merge point), fix the test's target to be explicit about what it actually needs to verify (a named revision boundary), rather than restructuring the migration graph to make the ambiguous shorthand resolve again.
- Add an automated regression test alongside any merge revision that walks a fresh database to only one sibling branch, then asserts `alembic upgrade head` picks up the other branch's DDL. This is the only way to pin "a partially-migrated database gets healed by upgrade head" as a checked invariant instead of something re-verified manually each time. Reusable pattern, adapted from `backend/tests/services/test_master_profile_schema.py:212-234`:

```python
def test_merge_revision_heals_a_database_stuck_on_only_the_sent_to_email_branch(migration_db) -> None:
    alembic_cfg, engine = migration_db

    # Walks ONLY the sent_to_email branch, mirroring a database that ran
    # `alembic upgrade head` back when that revision was itself a head -
    # never touching the sibling `17c15ce91b4e` branch at all.
    upgrade(alembic_cfg, "7b2f5c9d1a34")

    with engine.connect() as conn:
        columns_before = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
    assert "languages_json" not in columns_before, "test setup must reproduce the pre-merge, single-branch state"

    upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        master_profile_columns = {col["name"] for col in sa.inspect(conn).get_columns("master_profiles")}
        application_columns = {col["name"] for col in sa.inspect(conn).get_columns("applications")}

    # The previously-missing sibling branch's DDL is now present ...
    for column in ("photo_path", "photo_filename", "languages_json", "projects_json", "template_id"):
        assert column in master_profile_columns
    # ... without losing the already-applied branch's DDL.
    assert "sent_to_email" in application_columns
```

This test was confirmed to FAIL against the broken (rebased) graph and PASS against the fixed (merge) graph, by temporarily reintroducing the rebase and re-running it — giving future graph changes in this migration history a concrete tripwire instead of relying on someone remembering this incident.

## Related Issues

- [Stale Docker image and a squatted dev-server port mimic routing/CORS bugs](../developer-experience/stale-docker-image-and-squatted-dev-port-mimic-code-bugs.md) — same investigation, different mechanism. That doc covers why the docker-compose backend container was serving stale pre-merge code (the operational half of the incident, which produced the visible frontend crash); this doc covers the migration-graph defect discovered underneath it, which meant even a freshly rebuilt container's database would not have received the sibling migration's DDL.
