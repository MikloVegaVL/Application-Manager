# Residual Review Findings: Portal Application Auto-Fill Agent

Source: `ce-code-review` run, branch `feat/portal-application-auto-fill-agent`, head `ccb1e70`.
Plan: `docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md`

Two P0s and four P1s from this review (banked-resume race skipping the mandatory pre-submit
confirmation; delete-mid-run causing an untracked real submission; cancel-during-pause no-op;
substring-matched Personio iframe selector; unguarded DB write in terminal cleanup; plus two
testing-coverage P1s) were fixed and verified before this record — see commit `ccb1e70` and the
two filed issues below. Everything in this file is what remained after that.

## Filed (downstream-resolver, tracked)

- **P2** `frontend/src/app/pages/applications/applications.component.ts:329` — `submittedDateLabel()` shows `automation_started_at` (run start), not the actual `PortalSubmission.submitted_at` (never exposed via `ApplicationRead`). GitHub Issue: https://github.com/MikloVegaVL/Application-Manager/issues/35
- **P1/P2 (4 items)** `backend/app/api/portal_fill.py:47`, `backend/app/services/portal_agents/personio.py:264`, `backend/app/services/portal_agents/session.py:170`, `backend/app/services/portal_agents/base.py:64` — concrete test-coverage gaps (branch coverage for `_build_personio_fields`, the freetext LLM-failure pause path, `launch()`'s post-enter cleanup except-block, and `locate_field`'s non-label fallbacks). GitHub Issue: https://github.com/MikloVegaVL/Application-Manager/issues/36

## Decision gates (human-owned, not auto-applied)

These are real, validated findings that need a product/design call rather than a mechanical fix, so the autonomous pipeline did not apply them. They did not block shipping this PR but should be triaged.

- **P2** `backend/app/services/portal_agents/session.py:86,147` + `backend/app/services/portal_agents/personio.py:99,192` + `backend/app/api/portal_fill.py:94` (maintainability-reviewer) — three separate call sites reach into `session.py`'s underscore-prefixed module internals (`_active_sessions`/`_active_sessions_lock`, `_StopRun`, `_abort`). Each is individually documented as an intentional in-package convention, but the same encapsulation break was copied three times instead of exposed once. Suggested fix: add a small public `get_active_session(application_id)` accessor and make `_StopRun`/`abort` genuinely public if they're meant to be used from outside `session.py` — a design call on how much of this internal package boundary is worth formalizing for a personal-scale codebase.
- **P2** `frontend/src/app/pages/applications/applications.component.ts:429` vs `frontend/src/app/pages/application-editor/application-editor.component.ts:213` (maintainability-reviewer) — `pollPortalFillPhase()` reimplements `pollForRunningGeneration()`'s exact RxJS shape (same interval/timeout constants). A shared `pollUntil()` utility would remove the duplication but touches a different, already-shipped feature's component — a scope call, not a mechanical fix.
- **P2** `backend/app/api/portal_fill.py:74` / `backend/app/services/portal_agents/base.py:219` / `personio.py:124` (maintainability-reviewer) — `PersonioField.value: str | ProfileAttachment` and `upload_attachment_file(attachment: ProfileAttachment)` are fed a duck-typed `SimpleNamespace` at the CV-field call site. A `Protocol` would make the real two-attribute contract explicit; low urgency since it's internal and covered by tests.
- **P2** `backend/app/services/portal_agents/session.py:317`, called from `backend/app/api/portal_fill.py:99` (reliability-reviewer) — `start_session()`'s `launch_done.wait()` has no timeout, and `chromium.launch()` isn't given an explicit one either; a hung Chromium startup could block the request thread indefinitely. Needs a chosen timeout value and a decision on the resulting user-facing error.
- **P2** `backend/app/services/portal_agents/personio.py:319-327` (reliability-reviewer) — `_click_submit_button()` succeeding is treated as proof of submission; there is no check for a confirmation page or absence of validation errors on the portal's side. Verifying an arbitrary third-party portal's post-submit state is a genuinely open-ended problem across different Personio-hosted forms — deferring this is consistent with the plan's KTD10/KTD11 framing ("a cheap floor, not full verification"), but it's a real gap worth a product decision on how much verification v2 should attempt.

## Noted, not filed (accepted trade-offs / minor)

- `frontend/src/app/pages/applications/applications.component.ts:340` (testing-reviewer, P3) — the empty-URL/duplicate-click start guard and the three new HTTP-error snackbar branches (start/continue/cancel) are untested. Low value for a personal single-user app; revisit if this component grows more error paths.
- `backend/app/services/portal_agents/answering.py` shares the process-wide Ollama lock with cover-letter generation (learnings-researcher, citing `docs/solutions/performance-issues/ollama-concurrent-model-residency-memory-pressure.md`) — an accepted, already-documented trade-off (KTD6), not a new regression; a portal-fill run's freetext answering can now queue behind or block other in-flight AI features for the duration of one LLM call.
- Reliability's residual risks (cancel latency bounded by in-flight LLM/Playwright calls rather than a smaller value; a `None` profile/job_offer producing a generic rather than specific pause; the `SHUTDOWN_GRACE_SECONDS` vs. `PAUSE_TIMEOUT_SECONDS` mismatch on shutdown) are all consequences of decisions already made and documented in the plan (KTD2, KTD9) rather than new gaps.
- Adversarial's residual risks (a `uvicorn --reload` multi-process assumption; a theoretical double-fault resource leak if `close()` itself fails inside `_abort()`'s already-guarded cleanup) are narrow, low-likelihood dev-mode-only edge cases explicitly out of v1 scope per the plan's Risks & Dependencies section.
