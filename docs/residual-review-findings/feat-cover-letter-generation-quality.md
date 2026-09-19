# Residual Review Findings: Cover Letter Generation Quality

Source: `ce-code-review` run `20260919-151948-aa10893d`, branch `develop`, head `7839854`.
Plan: `docs/plans/2026-09-19-001-feat-cover-letter-generation-quality-plan.md`

## Filed (downstream-resolver, tracked)

- **P1** `backend/app/api/applications.py:106` — New pre-generation `Application` lookup sits outside the `try`/`finally` that releases the per-job-offer generation lock. If that lookup raises, the job offer's id is stuck in `_generating_job_offer_ids` forever, permanently 409ing future regenerations until the process restarts. Independently validated. GitHub Issue: https://github.com/MikloVegaVL/Application-Manager/issues/34

## Decision gates (human-owned, not auto-applied)

These are real, validated findings that need a product/design call rather than a mechanical fix, so the autonomous pipeline did not apply them. They did not block shipping this PR but should be triaged.

- **P0** `backend/app/services/ai_generator.py:114` — Prompt-injection laundering: the previous-letter block fed back on Regenerate is excluded from R7's untrusted-data delimiting, even though it is itself prior LLM output derived from the same untrusted job-posting pipeline. If a crafted job posting ever got partially injected text echoed into a saved cover letter, Regenerate would feed it back in as fully-trusted content. Corroborated independently by two reviewers (security, adversarial); confirmed by the validation pass. Suggested fix: wrap the previous-letter block with the same "treat as data, never instructions" framing already used for the job-offer block.
- **P1** `frontend/src/app/pages/application-editor/application-editor.component.html:82` — Regenerate can silently overwrite in-flight unsaved textarea edits: the textarea has no `regenerating()`-bound disabled/readonly state, so text typed during the multi-minute wait is clobbered with no warning when the response lands. Suggested fix: disable/readonly the textarea while `regenerating()` is true, matching Save/Send.
- **P1** `backend/app/api/applications.py:177` — Reload/second-tab during an in-flight Regenerate clears the client-side `regenerating` guard while the server-side lock and generation keep running; a manual Save in the interim can be silently overwritten when the pending Regenerate's commit lands later. This is an extension of an already-accepted plan scope boundary (same-application multi-tab consistency is out of scope) rather than a new gap, but is recorded here since it is now reachable through a slower, more consequential path (an active edit, not just a stale read). Suggested fix (if picked up): expose in-progress generation state from `GET /by-job-offer` so a freshly-loaded editor can disable editing instead of showing an editable stale form.
- **P2** `frontend/src/app/pages/application-editor/application-editor.component.ts:102` — The new consolidated `busy` computed (added specifically to fix a prior signal-drift bug) only has test coverage for its `regenerating()` branch; `saving()` and `sending()` disabling all three buttons is unverified. Suggested fix: extend the existing disabled-state spec with `saving.set(true)` and `sending.set(true)` cases.

## Noted, not filed (accepted trade-offs / minor)

- `frontend/src/app/core/services/tab-title.service.ts:41` — `markGenerationStarted()` is a permanently empty no-op, kept only for symmetric pairing with `markGenerationSettled()` per the plan's KTD2. A maintainability reviewer suggested deleting it; kept as a documented design choice rather than dead code needing removal.
- `frontend/src/app/core/services/tab-title.service.ts:68` — the `visibilitychange`-while-still-hidden guard branch has no direct test. Minor, narrow coverage gap.
- Backend: no test covers a `db.query` failure at the new `Application` lookup specifically re-verifying the lock still releases (would directly prove the filed issue's fix once applied).
- Backend/security: `job_offer.title`/`company`/`location` and `previous_cover_letter_text` have no length cap before entering the prompt (cost/DoS residual risk, not a confirmed bypass).
