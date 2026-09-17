# Residual Review Findings

Branch: `feat/applications-manual-job-offer`
Head at time of review: `a0483dae769480634ccc1d2f096fe74a19524996`
Plan: `docs/plans/2026-09-15-005-feat-applications-manual-job-offer-plan.md`

`ce-code-review` ran with the full reviewer roster (correctness, testing, maintainability, reliability, adversarial). One actionable finding was applied directly (whitespace-only required-field validation, `fix(review)` commit). The finding below could not be auto-applied under LFG's confidence/agreement bar (anchor 75 without cross-persona agreement) and was filed as a tracker ticket instead.

## Filed

- P2 -- `frontend/src/app/pages/applications/applications.component.ts:181` -- Re-entrancy guard on the save-in-flight state is never exercised by a test -- https://github.com/MikloVegaVL/Application-Manager/issues/31

## Other findings (report-only, need human/product judgment)

These were not eligible for autonomous filing (owner: human) but are recorded here so they aren't lost:

- P2 -- `frontend/src/app/pages/applications/applications.component.ts:219` -- 409 conflict on a manually-entered offer silently redirects to a possibly-unrelated existing application, since the dedup key is free text the user typed rather than a real posting URL. Suggested direction: warn/confirm before redirecting instead of asserting "already saved." Does not conflict with the plan's settled decision to keep the reference field free text (KTD governing R2/R6) -- that decision is about accepting free text at all; this is about what happens on a genuine collision.
- P2 -- `frontend/src/app/pages/applications/applications.component.ts:212` -- No timeout on the manual job-save request can leave the "Add job offer" button permanently disabled if the request hangs. Left as a product/consistency decision rather than an isolated fix: the same gap already exists, unaddressed, in the pre-existing `job-search.component.ts` save/generate flows this code mirrors -- better fixed app-wide in one follow-up than diverged here.
