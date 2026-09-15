## Residual Review Findings

Source run: `ce-code-review mode:agent` on `feat/job-search-hide-applied` (plan: `docs/plans/2026-09-15-004-feat-job-search-hide-applied-plan.md`).

- P2 · `frontend/src/app/core/models/job-offer.model.ts:70` · Frontend treats guaranteed search-count field as optional — https://github.com/MikloVegaVL/Application-Manager/issues/26
- P2 · `frontend/src/app/core/services/job-search-state.service.ts:44` · Deleting an application leaves stale applied empty state — https://github.com/MikloVegaVL/Application-Manager/issues/27
- P2 · `backend/app/services/job_search_service.py:604` · Shared page source_url hides distinct postings — https://github.com/MikloVegaVL/Application-Manager/issues/28
- P3 · `frontend/src/app/core/services/job-search-state.service.ts:56` · Stale saved job id routes to a deleted job — https://github.com/MikloVegaVL/Application-Manager/issues/29

Review-driven fixes applied in `fix(review): apply review findings` (testing gaps T1–T4). No `settled_conflict`-stamped findings; no proceeded-and-flagged `settled_decision_conflicts`.
