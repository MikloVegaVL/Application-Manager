# Residual Review Findings — feat/job-search-application-email-lookup

Source run: `lfg` pipeline, branch `feat/job-search-application-email-lookup`, PR #24.
Scope: application-email lookup feature (plan `docs/plans/2026-09-15-002-feat-job-search-application-email-lookup-plan.md`).

## Applied

- Backend review fixes: SSRF parser-differential rejection, shared bounded lookup executor + cancellation flag, deadline returns an already-found candidate, `force` re-run support, `mailto:` collection, employer-domain restriction, residual-500 guards, download-time byte cap, verbatim boundary matching, persistence guards, `is_global` IP check.
- Frontend review fixes: `force` sent to the backend, dialog pre-fill gated on `status === 'found'`, plus new tests for HTTP-error mapping, save-time persistence, cache precedence, and cache clearing.
- Simplification pass: shared `is_public_ip` predicate, `dict.fromkeys` dedupe, payload helper, dead request fields removed, `text.lower()` hoist, unused `db.refresh` removed, cache clearing + docstring.

## Residuals (documented, not blocking)

- **In-flight Ollama call cannot be interrupted** (P1, partially mitigated). The cancellation flag stops all subsequent page work and a shared bounded executor prevents unbounded thread growth, but a single hung extraction holds the process-wide `_ollama_lock` until it returns. Fully fixing this needs a timeout parameter on `llm_client.generate_structured`, which was left untouched to avoid changing its public API.
- **Unbounded DNS resolution** (P2). `socket.getaddrinfo` has no timeout; resolution is bounded only by the overall lookup deadline. A wrapper would reintroduce the worker-leak class, so it was left as-is.
- **DNS-rebinding TOCTOU remains in principle** (P2, security). Validation resolves the host, then `requests` re-resolves when connecting. Redirects are disabled and backslash/whitespace/control-char URLs are rejected, but full mitigation requires IP pinning at connect time.
- **Serial page fetches** (efficiency suggestion, skipped). Bounded pages are fetched serially; a slow early page can consume the deadline. Acceptable given the page cap and deadline; concurrency was not added.
- **Duplicated status copy/markup** between `job-search.component.html` and `send-application-dialog.component.html` (maintainability suggestion, skipped). Not extracted into a shared presentational component.
- **Job-search URL validation tightened.** `validate_source_url` now rejects whitespace in URLs; one existing Xing test fixture used a raw-space href and was updated to a URL-safe slug.

## Notes

- Two pre-existing test failures are unrelated to this branch and also fail on the base branch: `backend/tests/api/test_profile.py::test_patch_profile_partial_payload_leaves_other_fields_untouched`, and the `SentEmailsComponent` export test.
- An unrelated, uncommitted `sent_emails` feature was present in the working tree during this run (edited by an external process). It was deliberately excluded from every commit on this branch.
