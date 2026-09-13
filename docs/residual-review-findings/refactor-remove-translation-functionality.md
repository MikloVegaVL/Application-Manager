# Residual Review Findings

Source: ce-code-review run `20260913-201005-25971a37`, branch `refactor/remove-translation-functionality`, base `e4fb40b` (merge-base with `develop`). Plan: `docs/plans/2026-09-13-005-refactor-remove-translation-functionality-plan.md`. Reviewers: correctness, testing, maintainability, data-migration, adversarial, learnings.

Applied in `bc871aa` (fix(review)): browser tab titles, CV-builder unsaved-changes confirm, application-editor subtitle, and the CV import/parse warning/error strings were still German. Remaining findings below were not applied.

## Filed

- P2 — `backend/app/services/file_validation.py:13` — Backend error `detail` strings are still German and surface in the English UI — https://github.com/MikloVegaVL/Application-Manager/issues/16
- P2 — `frontend/src/app/pages/cv-builder/sections/skills-section.component.ts:25` — CV skill-level label diverges between Builder form (`Basic knowledge`) and rendered PDF (`Basic`) — https://github.com/MikloVegaVL/Application-Manager/issues/17

## No durable sink (recorded inline)

- P3 — testing gap — no test asserts the header language switcher / translate affordances are absent (R1/R2/AE3).
- P3 — testing gap — hand-inlined interpolations (applications delete confirm, job-search saved snackbar, profile max-attachments message) have no assertions.
- P3 — testing gap — migration `581736b96da4` idempotency guards are only exercised both-present (upgrade) and both-absent (downgrade); the partial one-column state is untested.
- P3 — testing gap — no repo-wide guard prevents German user-facing strings outside the cover-letter path, which is how the route titles, guard confirm, editor subtitle, and import warnings escaped the removal.

## Residual risks

- P2 — Destructive-by-design migration: `581736b96da4.upgrade()` drops `content_language`/`content_translations_json`; `downgrade()` re-adds empty defaults only, so stored translations are unrecoverable. Accepted per the Product Contract. Verification is SQLite-only while production is PostgreSQL; the downgrade's `server_default` handling is unverified on the production dialect.
- P2 — Deploy ordering: dropping columns while an older build still selects them yields `UndefinedColumn` errors; the app changes in the same PR, but a migration-ahead-of-code deploy has a transient failure window.
- P3 — `SECTION_LABELS` (`cv-import.component.ts`) duplicates the four CV-builder tab labels with no shared source after the i18n removal.
- P3 — `backend/tests/services/test_llm_client.py` still exercises a batch-map schema with no production caller (shared `llm_client.py` intentionally untouched).
- P3 — callsite completeness for the removed translation surface is grep-only; a dynamically resolved reference could be missed.
- P3 — the post-review working-tree fixes (spec alignment + simplify cleanups) are committed by the shipping step; until then the committed branch's frontend suite was red.
- P3 — untracked `.simplify-scope.diff` at the repo root is a scratch artifact and must not be committed.

## Settled-decision conflicts

None.
