# Residual Review Findings

Source: `ce-code-review` (LFG pipeline) on branch `feat/job-search-broader-source-coverage`, plan `docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md`.

Applied in `fix(review): apply review findings` (commit on this branch): Adzuna error mapping, JSON-LD URL resolution/validation/cap, per-card salary/homeoffice, board detail-link requirement, per-card error isolation, one status per registration, inner-timeout clamp, `fallback_url`/`enrich_description` URL validation, and log URL sanitization.

The following actionable findings were **not** applied (design/behavior/security-posture decisions or advisory). They remain open.

## Residuals

- P1 `backend/app/services/job_sources/shared.py:136` — **Render semaphore scope / no acquire timeout.** The bounded Playwright semaphore is held for the whole render (launch + navigation + `page.content`) and acquired without a timeout, so concurrent searches plus `GET /jobs/{id}` detail loads can starve on the 2 permits; timed-out workers are not cancelled (`shutdown(wait=False)`). Proposed: acquire only around `chromium.launch()` (or bounded `acquire(timeout=remaining)` returning `timeout`), and route `fetch_description` through a separate bounded render queue. Needs a concurrency-design decision.
- P2 `backend/app/services/job_search_service.py:507` — **Fallback scraper runs after the shared deadline.** When Arbeitsagentur times out, the `fallback_url` scraper runs synchronously with its own 15s timeout, so total latency can reach deadline + 15s. Proposed: pass the remaining budget and skip the fallback when AA timed out/errored (only run on confirmed empty `ok`).
- P2 `backend/app/services/job_search_service.py:455` — **No global concurrency/rate cap per search.** Up to 13 blocking outbound calls per request with no queue or backpressure and no cancellation of timed-out workers; upstream rate-limit bans and thread/FD exhaustion are possible. Proposed: bounded shared pool / request rate limit.
- P2 `backend/app/services/job_sources/shared.py:232` — **`validate_source_url` bypassable via non-canonical IPs/DNS.** Numeric/octal/hex IPv4, IPv4-mapped IPv6, and hostnames resolving to private addresses pass. Proposed: resolve and re-validate addresses (mind TOCTOU/DNS rebinding) or restrict to an allowlist of known hosts.
- P2 `backend/app/schemas/job_offer.py:15` — **No validation at the save trust boundary.** `JobOfferCreate` accepts an arbitrary `source_url`/`source_platform`, which is the root enabler of the stored-SSRF chain. Proposed: `field_validator` calling `validate_source_url` and a `source_platform` allowlist, rejecting with 422 before persistence.
- P3 `backend/app/services/job_sources/shared.py:298` — **Heuristic dedup keys on title alone**, dropping distinct postings with the same title across a page. Proposed: key on `(title, company, location)` or resolved `source_url`.
- P3 `backend/app/services/job_sources/adzuna.py:152` — **Adzuna does not enforce `result_cap` client-side** (server hint only), unlike Jooble/LinkedIn. Proposed: break at the cap.
- Advisory `backend/app/services/job_search_service.py:301` — **Fallback `GenericJobScraper` default 15s timeout is not bounded by the shared deadline** (see the fallback residual above).

## Testing gaps (not applied)

- No test for semaphore starvation / hung Playwright launch / thread cleanup after deadline.
- No test for duplicate-`SOURCE_PLATFORM` handling beyond the one added for registrations (now covered at the service level).
- No test for `validate_source_url` non-canonical IP encodings or DNS-resolved private hosts.
- Board search-URL patterns for kimeta/germantechjobs/jobware/programmiererjobboerse/it-entwickler-jobs are best-known guesses; live behavior is unverified.
- Adzuna `_format_salary` min-only/max-only/non-numeric branches; JSON-LD list/`hiringOrganization`-as-string branches.

## Notes

- Two pre-existing SSRF surfaces (`fallback_url` server-side fetch and stored `source_url` rendered for `xing`) are now guarded by `validate_source_url` at the call sites, but the save-boundary allowlist residual above remains.
- Backend suite at record time: 255 passed. Frontend: 77 passed, production build succeeds.
