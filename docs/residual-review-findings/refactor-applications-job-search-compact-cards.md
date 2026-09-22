# Residual Review Findings

- Source run: `ce-code-review` run `20260922-194651-04688a6e`, branch `refactor/applications-job-search-compact-cards` @ `ed5914e97ed4bf4e363233bcd297997d4a496d4e`
- Plan: `docs/plans/2026-09-22-002-refactor-applications-job-search-compact-cards-plan.md`
- Applied in-line during the pipeline: finding #2 (disabled-item tooltip never rendered — `fix(review): disabled menu items never showed their tooltip`, commit `ed5914e`)

## Filed

- P1 — `frontend/src/app/pages/applications/applications.component.ts:700` — Busy/disabled-state test coverage gaps across the compact-card redesign — https://github.com/MikloVegaVL/Application-Manager/issues/40
- P2 — `frontend/src/app/pages/job-search/job-search.component.ts:280` — Job search busy-indicator test for Generate is confounded by a redundant binding — https://github.com/MikloVegaVL/Application-Manager/issues/41
- P2 — `frontend/src/app/shared/compact-card/compact-card.component.html:42` — Link-vs-anchor rendering branch duplicated twice in compact-card.component.html — https://github.com/MikloVegaVL/Application-Manager/issues/42

## Failed

(none)

## No sink

(none — GitHub Issues was available via `gh` and all three findings were filed there)
