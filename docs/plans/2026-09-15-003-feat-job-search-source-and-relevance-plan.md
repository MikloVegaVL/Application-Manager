---
title: Job Search Source Restoration and Relevance Filter - Plan
type: feat
date: 2026-09-15
topic: job-search-source-and-relevance
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
deepened: 2026-09-15
---

# Job Search Source Restoration and Relevance Filter - Plan

## Goal Capsule

- **Objective:** Restore Adzuna and Jooble as job search sources, and add one shared relevance filter applied to every source's merged results — replacing the current per-source, inconsistent filtering.
- **Product authority:** Scope confirmed with the user via `ce-brainstorm` dialogue on 2026-09-15. The job-search component's UI/UX is not active scope here — see How This Work Fits Together. Google Custom Search was in scope earlier in this dialogue and was dropped after planning research found it infeasible — see Scope Boundaries.
- **Open blockers:** None.

## Product Contract

**Product Contract preservation:** unchanged. Requirements R1-R9 and Key Decisions carry forward verbatim from the corrected `ce-brainstorm` version; this enrichment only adds the Planning Contract and Implementation Units below.

### Summary

Reverse part of today's source consolidation by restoring Adzuna and Jooble, and introduce a single shared keyword-relevance filter applied uniformly to every source's merged results.

### Problem Frame

Earlier today, one plan landed that removed Adzuna, Jooble, and Kimeta in favor of fewer sources to maintain, followed by a separate, undocumented commit that dropped StepStone, GermanTechJobs, and Indeed for the same reason. That pruning addressed maintenance surface, but left two other pains unaddressed: search results that don't match the query well, and good jobs that don't surface at all. Restoring two of the credentialed sources trades back some of that maintenance surface for coverage, and a shared relevance filter targets the match-quality problem directly instead of leaving it to each source's own (inconsistent) search quality.

### Requirements

**Source lineup**

- R1. Restore `AdzunaJobsClient` as a job search source: settings-based credentials (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`), an enable flag (`JOB_SEARCH_ADZUNA_ENABLED`), and the same German-market search behavior it had before removal (`GET https://api.adzuna.com/v1/api/jobs/de/search/1` with `app_id`, `app_key`, `what`, `where`, `results_per_page` — confirmed current against Adzuna's official developer docs).
- R2. Restore `JoobleJobsClient` as a job search source: settings-based credential (`JOOBLE_API_KEY`) and an enable flag (`JOB_SEARCH_JOOBLE_ENABLED`), matching its pre-removal behavior.
- R3. Kimeta stays removed — not restored.
- R4. Adzuna and Jooble each participate in the existing search fan-out and graceful-degradation behavior (a missing/rejected credential or an unreachable source doesn't fail the overall search or the other sources) the same way every other source does.
- R5. No further pruning of the remaining scraper-based sources (LinkedIn, Xing, devjobs, programmiererjobboerse) — today's pruning is considered complete.

**Relevance filtering**

- R6. Add one shared relevance filter applied once, after all sources' results are merged, to every source's results uniformly (including sources with their own server-side search).
- R7. A result passes the filter when every keyword term in the search query appears, case-insensitively, in the result's title or description text.
- R8. Remove Arbeitnow's existing private per-source keyword filter — the shared filter (R6/R7) supersedes it, so the Arbeitnow client goes back to a plain fetch-and-map.

**Historical data**

- R9. The source-label map keeps its `adzuna`, `jooble`, and `kimeta` entries (already the case from the prior removal) so historical Applications and SentEmail records keep readable labels. No change needed — already true.

### Key Decisions

- **Restore Adzuna and Jooble, keep Kimeta removed.** (session-settled: user-directed — chosen over leaving today's full consolidation in place.) Governs R1, R2, R3.
- **Google Custom Search is dropped from scope entirely**, not merely deferred. (session-settled: user-directed — chosen over pursuing an alternative Google-adjacent source, e.g. a paid third-party Google-Jobs scrape service, Vertex AI Search, or a direct scrape of Google's results page, after the credentialed-API path the user originally chose turned out to be infeasible: the Google Custom Search JSON API is closed to new customers as of 2026-09-15, and this codebase has no pre-existing account or credentials for it.) Governs Scope Boundaries.
- **Relevance is enforced by one shared post-merge filter, not per-source tuning.** (session-settled: user-directed — chosen over fixing each source's own matching individually.) Governs R6, R7, R8.
- **The shared filter matches on title-or-description (looser), not title-only (stricter).** (session-settled: user-directed — chosen to minimize the risk of silently dropping a relevant job whose title is phrased differently, accepting more borderline results as the trade-off.) Governs R7.
- **LinkedIn and the other remaining scrapers (Xing, devjobs, programmiererjobboerse) are not pruned further.** (session-settled: user-directed — LinkedIn was raised as a candidate and explicitly kept.) Governs R5.

### Scope Boundaries

- Cross-source deduplication stays deferred, continuing the posture set by two prior plans (`docs/plans/2026-08-12-...-external-platforms-plan.md`, `docs/plans/2026-09-11-...-broader-source-coverage-plan.md`).
- No further removal of LinkedIn, Xing, devjobs, or programmiererjobboerse (R5).
- Per-source location filtering is untouched — this plan's shared filter covers keyword relevance only (R6, R7); Arbeitnow's location-substring check is explicitly preserved as local logic (see U4/KTD9).
- **Google is not a job search source in this plan, in any form.** It was explored earlier in this dialogue as a Custom-Search-API-backed source restricted to a curated job-site list, but the Custom Search JSON API turned out to be closed to new customers (existing customers have until 2027-01-01 to migrate off it; this codebase was never a customer). No substitute Google-adjacent approach (paid scrape service, Vertex AI Search, direct scrape) was evaluated or chosen — revisit as a fresh brainstorm topic if Google coverage is still wanted.

<!-- ce-section: work-relationships -->
### How This Work Fits Together

This plan owns backend search-result quality: the Adzuna/Jooble source restoration and the shared relevance filter. The original request also raised the job-search component's frontend UI/UX (making it "leaner"), which the user chose to keep out of this plan, and a Google source (dropped — see Scope Boundaries). This breakdown is the current understanding, not a committed roadmap:

- Job-search component UI/UX (frontend leanness, layout, flow) — Can proceed independently of this plan. Not yet its own brainstorm.
- A Google-backed job search source — Not pursued in this plan; would need its own brainstorm to pick a feasible approach (see Scope Boundaries).

### Sources / Research

- `backend/app/services/job_sources/boards.py` (current) — confirms only `programmiererjobboerse` remains in `BOARD_DESCRIPTORS`; StepStone, GermanTechJobs, and Indeed were dropped by commit `f912428`, after and not covered by the `2026-09-15-001` consolidation plan.
- `git log --oneline -- backend/app/services/job_sources/boards.py` — `01f28ba` ("feat(job-search): remove Adzuna, Jooble, and Kimeta sources") removed all three; `cac36b8` ("feat(job-search): add Adzuna API source (U4)") is the last commit with a working `adzuna.py`; Jooble's equivalent last-working commit is `2fd83c1`.
- `git show cac36b8:backend/app/services/job_sources/adzuna.py` and `git show 2fd83c1:backend/app/services/job_sources/jooble.py` — full pre-removal implementations, fully read during planning research. Both use a hand-rolled class-level `_cooldown_until` cooldown (predates today's `CooldownMixin`), `is_configured()`/`SourceNotConfiguredError` gating, and inconsistent unexpected-error handling (Adzuna returns `[]`, Jooble raises `RuntimeError`) — see KTD1/KTD2.
- `git show cac36b8:backend/tests/services/job_sources/test_adzuna.py` and `git show 2fd83c1:backend/tests/services/job_sources/test_jooble.py` — full pre-removal test suites, fully read during planning research; structure to mirror (see U1/U2 Patterns to follow).
- [Adzuna Developer Overview](https://developer.adzuna.com/overview) and its search-endpoint docs — confirm the endpoint pattern `https://api.adzuna.com/v1/api/jobs/{country}/search/{page}` with required `app_id`/`app_key`, and optional `what`, `what_exclude`, `where`, `results_per_page`, `sort_by`, `salary_min`, `salary_max`, `full_time`, `permanent` — the pre-removal implementation's parameter usage matches this current documentation.
- [Google Custom Search JSON API overview](https://developers.google.com/custom-search/v1/overview) — confirms "The Custom Search JSON API is closed to new customers" and "not available for new customers"; existing customers have until 2027-01-01 to transition off it. This is why Google was dropped from scope rather than implemented.
- `backend/app/core/config.py:93-113` — current settings confirm `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`/`JOOBLE_API_KEY` and their enable flags no longer exist (fully removed by `01f28ba`); line 112 is the natural insertion point for their restored block, ahead of the `# --- Bewerbungs-E-Mail-Suche ---` section starting at line 113. No `GOOGLE_CSE_*` settings exist anywhere, confirming a Google signup would have been new-customer.
- `backend/app/services/job_search_service.py:45-524` (`_build_default_registry`, `search`) — confirms the current live registry pattern (credential-less sources unconditional at lines 338-349, flag-gated sources at lines 350-358) and the fan-out/merge structure: per-source merge at line 481 (`results.extend(offers)`), fallback-scraper merge at line 509, and **two return points** — an early exit at line 505 (invalid `fallback_url`, skips the fallback but still returns fan-out results) and the final return at line 524. Both must route through the new shared filter — see U3/KTD7.
- `backend/app/services/job_sources/arbeitnow.py:38-150` (`ArbeitnowJobsClient`, `_matches`) — confirms `_matches` does two independent things: keyword AND-matching against `title`/`description`/`company_name` (lines 140-145), and a separate `location_term` substring check against `raw.get("location")` (lines 146-149). Only the keyword half is superseded by R6/R7 — see U4/KTD9/KTD10.
- `backend/app/services/job_sources/shared.py` — `CooldownMixin` (lines 50-79), `redact_credentials()` (lines 290-293, only matches query-param-style secrets — doesn't catch Jooble's URL-path key), `validate_source_url()` (lines 361-398), `fold_salary_homeoffice()`, `strip_html()` — all reused by the restored clients, unchanged.
- `backend/tests/services/test_job_search_service.py` (639 lines) — `_FakeClient`/`_offer`/`_service` test-double conventions (lines 21-117; `_offer()`'s default title is `"Some Job"` with `description_text=None`); `test_default_registry_is_built_from_settings_without_injection` needs registry-membership updates (U1/U2). Separately, six existing tests assert directly on `response.results` content against keyword searches (e.g. `service.search("Angular", ...)`) whose `_offer()` fixtures don't contain that keyword in title or description — once U3's shared filter lands, all six will start failing, not just `test_happy_path_combines_results_and_marks_all_sources_ok` — see U3.
- `frontend/src/app/core/utils/source-label.util.ts:7-17` — confirms `adzuna: 'Adzuna'` and `jooble: 'Jooble'` already exist in `SOURCE_LABELS` (R9 is already satisfied, no frontend change needed).
- Flow-analysis pass (spec-flow-analyzer, run during planning) — surfaced three behavior-shaping gaps in R6/R7's literal wording, resolved as KTD4-KTD6 below: (1) several sources (Arbeitsagentur, LinkedIn, heuristic board/Xing cards) have no `description_text` at filter time, so the filter degenerates to title-only for them regardless of the "title-or-description" wording; (2) per-source `SourceStatus` is computed before the filter runs, so a source can report `ok` while contributing zero visible results; (3) the Arbeitsagentur-empty fallback-scraper trigger must be decided as pre- or post-filter, since post-filter would materially increase how often the generic scraper fires against a user-supplied URL.
- `docs/plans/2026-09-15-001-feat-job-search-source-consolidation-plan.md` — the plan that removed Adzuna/Jooble/Kimeta and added Arbeitnow; this plan partially reverses it (Adzuna, Jooble) while leaving the Arbeitnow addition and Kimeta removal in place.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Restored `AdzunaJobsClient`/`JoobleJobsClient` use `CooldownMixin` instead of the pre-removal hand-rolled class-level `_cooldown_until` field.** `CooldownMixin` is the codebase's current shared idiom (already used by `ArbeitnowJobsClient`) and predates neither client's removal by coincidence — it was introduced after them. Governs U1, U2.
- KTD2. **Both restored clients raise `RuntimeError` on unexpected (non-401/403/410/429) errors, matching Arbeitnow's current behavior, rather than Adzuna's old silent `return []`, and every such raise uses `raise ... from None`.** The orchestrator's existing `except Exception` handling (`job_search_service.py:470-475`) already maps this to `reason="error"` consistently for every source; Adzuna's old inconsistency (vs. Jooble's own `RuntimeError`) was an artifact of when it was written, not a deliberate choice. The `from None` suppression is load-bearing, not stylistic: `redact_credentials()` only covers each client's own explicit `logger.warning()` calls — it never touches Python's exception-chaining/traceback formatting, and the orchestrator's blanket `except Exception: logger.exception(...)` (`job_search_service.py:470`) logs the full chained traceback. Without `from None`, the original `requests.RequestException` (whose `str()` carries the raw, credential-bearing URL — Adzuna's `app_key` query param or Jooble's URL-path key) would appear in that traceback in plaintext, bypassing the redaction Adzuna/Jooble's own logging already applies. Jooble's pre-removal implementation already used `from None` at all three raise sites; Adzuna's KTD2-mandated `RuntimeError` (new code — the pre-removal client silently returned `[]` instead) must adopt it explicitly, not as an afterthought. `from None` alone is not sufficient: it only suppresses the *chained* exception, not the new `RuntimeError`'s own message. The message text at every raise site must be a static string or already-redacted (`redact_credentials(str(exc))`), never a raw f-string/format interpolation of the caught exception — otherwise the credential leaks via the new exception's own `str()` instead of via chaining, defeating the same protection a different way. Governs U1, U2.
- KTD3. **The shared filter's term-matching logic (case-insensitive, all keyword terms required, checked against a joined title+description string) generalizes the keyword half of Arbeitnow's existing `_matches`**, rather than inventing new matching logic. Governs R7, U3.
- KTD4. **A missing/`None` description degrades the filter to title-only matching for that result, with no special-casing.** Flow analysis found `description_text` is `None` at filter time for Arbeitsagentur, LinkedIn, and heuristically-scraped board/Xing results (only Adzuna/Jooble/Arbeitnow/devjobs and JSON-LD-extracted results populate a description). R7's "title or description" wording already covers this: an absent description simply narrows the check to title, it doesn't exempt the result from filtering. Governs R7, U3.
- KTD5. **Per-source `SourceStatus`/`reason` continues to reflect pre-filter (raw) results, unchanged from today** — the filter only changes what appears in `results`, not a source's own status. A source whose raw hits are all filtered out as irrelevant still reports `ok`. This is the smallest-diff option (no `SourceStatus.reason` schema change) and matches R6's literal "applied once after merge" wording. Governs R6, U3.
- KTD6. **The Arbeitsagentur-empty fallback-scraper trigger (`job_search_service.py:493`) keeps evaluating pre-filter `arbeitsagentur_results`, not post-filter.** Since Arbeitsagentur has no description at filter time (KTD4), a post-filter check would raise how often the generic fallback scraper fires against a user-supplied URL — a real behavior and load change, not just a display nuance. Pre-filter preserves today's trigger frequency. Governs U3.
- KTD7. **`search()` is refactored so every path out of the method applies the filter exactly once before constructing `JobSearchResponse`, by collapsing the current early-exit guard into an if/else whose branches converge on one shared tail.** The existing early return at `job_search_service.py:505` is not an independent branch — it's the body of a security guard (`if not validate_source_url(fallback_url): ...`) that exists specifically to prevent the fallback scraper from ever being called with a rejected URL. Naively deleting that early `return` and falling through would defeat the guard and call the fallback scraper with an unsafe URL. The correct refactor turns the guard into `if not validate_source_url(fallback_url): ... else: <existing fallback-scraper body>`, so both branches fall through to one shared tail (`results = self._apply_relevance_filter(...)`, then one `return JobSearchResponse(...)`) — this is simpler than extracting a separate `_finalize()` helper and is the preferred shape, not one of two equally-weighted options. The refactor legitimately collapses `search()` to a single `return` statement; downstream verification wording must not assume two return statements survive (see Verification Contract). Governs R6, U3.
- KTD8. **One aggregate info-level log line reports the filter's kept/dropped counts.** `search()` currently has exactly one `logger.info()` call (the fallback-scraper trigger message) — it is not count-oriented, so this is a new logging shape for the method rather than mirroring an existing one, but it follows the same `logger.info()`-for-notable-orchestration-events convention that call already establishes. This is a one-line addition addressing the debuggability gap flow analysis raised for a global filter that can now silently remove previously-visible results from any source. Governs U3.
- KTD9. **Arbeitnow's location-substring check is preserved as small standalone logic in `search()` after `_matches`'s keyword half is removed**, per the existing Scope Boundary that location filtering stays untouched. Governs R8, U4.
- KTD10. **Arbeitnow's `company_name`-only matching is accepted as narrowed, not preserved.** `_matches` today also matches on `company_name` (independent of title/description); the shared filter (R7) does not. This narrows what Arbeitnow-sourced results the shared filter will keep, specifically for a search that only matches a company name — an accepted, explicitly documented trade-off rather than a silent behavior change. Governs R8, U4.

### Assumptions

- Adzuna's and Jooble's API shapes (endpoint, parameters, response fields) are assumed unchanged since their pre-removal implementations (commits `cac36b8`/`2fd83c1`); Adzuna's shape was independently reconfirmed against current official docs during the originating brainstorm. Re-verify both live during implementation before finalizing `_map_offer` field mappings. This includes each API's actual rate-limit policy — `CooldownMixin`'s cooldown duration (KTD1) is assumed transferable from Arbeitnow's usage without confirming it matches Adzuna's or Jooble's real backoff requirements.
- Whether Adzuna's or Jooble's own server-side search (`what`/`where` and Jooble's equivalent) does synonym or stemming matching beyond literal substrings is unknown; if so, the shared filter's literal-substring check could drop some of their genuine server-matched results. No mitigation is planned for this here — noted as a residual risk.

---

## Implementation Units

### U1. Restore Adzuna as a job search source

- **Goal:** Restore `AdzunaJobsClient` on the standard `SOURCE_PLATFORM` + `search()` contract, credential-gated and registered like every other credentialed source.
- **Requirements:** R1, R4
- **Dependencies:** None
- **Files:**
  - `backend/app/services/job_sources/adzuna.py` (restore, adapted per KTD1/KTD2)
  - `backend/app/core/config.py` (restore `JOB_SEARCH_ADZUNA_ENABLED`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` at line 112, ahead of the existing `# --- Bewerbungs-E-Mail-Suche ---` block)
  - `backend/app/services/job_search_service.py` (import `AdzunaJobsClient`; add its flag-gated registration in `_build_default_registry()`, alphabetically before `arbeitnow`)
  - `backend/tests/services/job_sources/test_adzuna.py` (restore, adapted per KTD1/KTD2)
  - `backend/tests/services/test_job_search_service.py` (add `"adzuna"` to the expected default-registry platform set)
  - `backend/.env.example` (restore `JOB_SEARCH_ADZUNA_ENABLED`/`ADZUNA_APP_ID`/`ADZUNA_APP_KEY` example lines)
- **Approach:**
  1. Restore `adzuna.py` from `git show cac36b8:backend/app/services/job_sources/adzuna.py`, then apply KTD1 (swap the hand-rolled cooldown for `CooldownMixin`) and KTD2 (raise `RuntimeError` on unexpected errors instead of returning `[]`).
  2. Restore the settings block in `config.py` verbatim (see Sources / Research for the exact historical block).
  3. Add the import and a flag-gated registration block in `_build_default_registry()`: the `if settings.JOB_SEARCH_ADZUNA_ENABLED:` wrapper mirrors `LinkedInJobsClient`'s registration shape (`job_search_service.py:350-358`), but the constructor call must also pass `timeout=inner_timeout_for(self._deadline_seconds)` like Arbeitnow's registration does (`job_search_service.py:338-349`) — LinkedIn's own registration doesn't pass a timeout kwarg and isn't the pattern for that part.
  4. Restore and adapt the test suite from `git show cac36b8:backend/tests/services/job_sources/test_adzuna.py`, updating the cooldown-reset fixture for `CooldownMixin` and the unexpected-error test for `RuntimeError` (raised via `from None`, per KTD2).
  5. Add `"adzuna"` to `test_job_search_service.py`'s default-registry platform assertions.
  6. Restore the three example lines in `.env.example`.
- **Patterns to follow:** `backend/app/services/job_sources/arbeitnow.py` (`CooldownMixin` usage, constructor shape, `RuntimeError`-on-error idiom, and its registration block at `job_search_service.py:338-349` for the `timeout=inner_timeout_for(...)` kwarg); `backend/app/services/job_search_service.py:350-358` (only for the `if settings.X_ENABLED:` flag-gating wrapper shape — LinkedIn's registration itself doesn't demonstrate the timeout kwarg).
- **Test scenarios:**
  - Happy path: `search("python", "Berlin")` returns mapped `JobOfferCreate` objects for sample results (requests_mock fixture).
  - Happy path: a result with salary fields folds into `description_text` via `fold_salary_homeoffice()`.
  - Edge case: a result with an unsafe/invalid `redirect_url` is dropped (parametrized over `validate_source_url`'s rejection cases).
  - Edge case: `is_configured()` returns `False` and `search()` raises `SourceNotConfiguredError` without making an HTTP call, when credentials are missing.
  - Error path: HTTP 401/403/410 raises `SourceNotConfiguredError` (credentials rejected).
  - Error path: HTTP 429 triggers `CooldownMixin`'s cooldown; a subsequent call within the cooldown window is skipped.
  - Error path: an unexpected HTTP error or network failure raises `RuntimeError` (KTD2), which the orchestrator maps to `reason="error"`.
  - Error path: `app_key` never appears in a logged URL or exception message (redaction).
  - Error path: when the orchestrator catches the unexpected-error `RuntimeError` and logs it via `logger.exception()`, the fully rendered traceback (assert via `caplog`, not just the client's own log message) never contains `app_key` — proves both that `raise ... from None` suppresses the chained original exception AND that the `RuntimeError`'s own message text isn't a raw interpolation of the credential-bearing exception (KTD2).
  - Integration: `_build_default_registry()` includes `"adzuna"` when `JOB_SEARCH_ADZUNA_ENABLED=True` and credentials are set; excludes it when the flag is `False`.
- **Verification:** `pytest backend/tests/services/job_sources/test_adzuna.py` and the full `pytest` run (from `backend/`) pass.

### U2. Restore Jooble as a job search source

- **Goal:** Restore `JoobleJobsClient` on the standard `SOURCE_PLATFORM` + `search()` contract, credential-gated and registered like every other credentialed source.
- **Requirements:** R2, R4
- **Dependencies:** None
- **Files:**
  - `backend/app/services/job_sources/jooble.py` (restore, adapted per KTD1/KTD2)
  - `backend/app/core/config.py` (restore `JOB_SEARCH_JOOBLE_ENABLED`, `JOOBLE_API_KEY`, same block as U1)
  - `backend/app/services/job_search_service.py` (import `JoobleJobsClient`; add its flag-gated registration, alphabetically between `devjobs` and `linkedin`)
  - `backend/tests/services/job_sources/test_jooble.py` (restore, adapted per KTD1/KTD2)
  - `backend/tests/services/test_job_search_service.py` (add `"jooble"` to the expected default-registry platform set)
  - `backend/.env.example` (restore `JOB_SEARCH_JOOBLE_ENABLED`/`JOOBLE_API_KEY` example lines)
- **Approach:**
  1. Restore `jooble.py` from `git show 2fd83c1:backend/app/services/job_sources/jooble.py`, then apply KTD1 (swap cooldown mechanism) and confirm KTD2's `raise ... from None` requirement — Jooble already raised `RuntimeError` pre-removal and already used `from None` at all three raise sites, so this is a preserve-don't-drop check during the `CooldownMixin` edit, not new behavior.
  2. Restore the settings block in `config.py` (same insertion point as U1, or combined into one edit if U1 and U2 land together).
  3. Add the import and flag-gated registration in `_build_default_registry()`, passing `timeout=inner_timeout_for(self._deadline_seconds)` per the same reasoning as U1 step 3 (mirror Arbeitnow's registration shape at `job_search_service.py:338-349`, not LinkedIn's, for the constructor-argument part).
  4. Restore and adapt the test suite from `git show 2fd83c1:backend/tests/services/job_sources/test_jooble.py` for `CooldownMixin`.
  5. Add `"jooble"` to `test_job_search_service.py`'s default-registry platform assertions.
  6. Restore the two example lines in `.env.example`.
- **Patterns to follow:** Same as U1, including `job_search_service.py:338-349` for the registration's `timeout` kwarg. Additionally: Jooble's API key sits in the URL path (not a query param), so `redact_credentials()`'s query-param regex does not catch it — the raw endpoint must never be logged at all, not just redacted (carry forward this existing safeguard from the pre-removal implementation).
- **Test scenarios:**
  - Happy path, salary folding, unsafe-URL rejection, not-configured, credential-rejected, 429-cooldown, unexpected-error — same shape as U1's list, adapted to Jooble's request/response shape.
  - Log redaction: confirm the raw endpoint (containing the API key in its path) is never logged, even at DEBUG level — distinct from U1's query-param redaction test, since Jooble's credential placement defeats `redact_credentials()`'s regex.
  - Error path: the unexpected-error `RuntimeError`'s `from None` suppression survives the `CooldownMixin` edit — the orchestrator's `logger.exception()` traceback (via `caplog`) never contains the API key, matching U1's equivalent test (KTD2).
  - Integration: `_build_default_registry()` includes `"jooble"` when configured and enabled.
- **Verification:** `pytest backend/tests/services/job_sources/test_jooble.py` and the full `pytest` run pass.

### U3. Add the shared post-merge relevance filter

- **Goal:** Implement one relevance filter (R6/R7) applied exactly once to the fully-merged search results, reachable from both of `search()`'s return paths, without changing per-source status semantics or the fallback-trigger condition.
- **Requirements:** R6, R7
- **Dependencies:** None (independent of U1/U2; benefits from their descriptions once landed, but doesn't require them)
- **Files:**
  - `backend/app/services/job_search_service.py`
  - `backend/tests/services/test_job_search_service.py`
- **Approach:**
  1. Implement a small pure helper (e.g. `_apply_relevance_filter(results, keywords)`) generalizing Arbeitnow's existing keyword-matching logic (KTD3): split `keywords` on whitespace, lowercase, require every term to appear in the joined title+description text; an empty term list passes everything through unfiltered (mirrors Arbeitnow's current behavior for a blank query). This is a deliberate first-of-its-kind placement — today every bare pure function in this codebase lives in `job_sources/shared.py`, and `job_search_service.py` has none — justified because the filter's only caller is `search()` itself and it operates on merged, cross-source `JobOfferCreate` results rather than per-source raw payloads, which is `shared.py`'s domain.
  2. A missing/`None` description degrades the check to title-only for that result (KTD4) — no special-casing needed, just treat `None` as an empty string before the join.
  3. Compute per-source `SourceStatus` from raw (pre-filter) offers, unchanged from today (KTD5).
  4. Keep the Arbeitsagentur-empty fallback-scraper trigger evaluating pre-filter `arbeitsagentur_results` (KTD6).
  5. Refactor `search()` per KTD7: turn the existing `if not validate_source_url(fallback_url): ... return ...` guard into an `if/else` whose `else` branch holds the existing fallback-scraper body, so both branches fall through to one shared tail — a single filter call followed by a single `return JobSearchResponse(...)`. The security intent of the original guard (never call the fallback scraper with a rejected URL) is preserved by the `else`, not by deleting the early return.
  6. Add one aggregate info-level log line reporting kept/dropped counts (KTD8).
  7. Update every existing test in `test_job_search_service.py` that asserts on `response.results` content against a keyword search (not just `test_happy_path_combines_results_and_marks_all_sources_ok`) so its `_offer()` fixtures contain the searched keyword in title or description — otherwise the new filter silently empties `response.results` in those tests and they fail for a reason unrelated to what they're testing. Either give the affected `_offer()` calls a title containing the test's search keyword, or introduce a keyword-agnostic fixture/assertion helper.
- **Technical design:**

  ```mermaid
  flowchart TD
      A[search request] --> B[fan out to sources]
      B --> C[per-source status from raw offers - KTD5]
      C --> D[merge raw offers into results]
      D --> E{arbeitsagentur_results raw empty AND fallback_url valid? - KTD6}
      E -- no / invalid fallback_url --> F[apply relevance filter once - KTD7]
      E -- yes --> G[run fallback scraper, extend results]
      G --> F
      F --> H[return JobSearchResponse: filtered results + pre-filter statuses]
  ```

  This closes the two-return-point gap by construction: the guard that used to `return` early (invalid `fallback_url`) becomes the "no / invalid fallback_url" branch of an if/else, so it and the fallback-scrape branch both converge on the single filter step and the single `return` at the end — `search()` ends with one return statement, not two.
- **Patterns to follow:** `backend/app/services/job_sources/arbeitnow.py`'s `_matches` (term-matching logic being generalized); the existing info-level count log near `search()`'s current final return (KTD8's logging style).
- **Test scenarios:**
  - Happy path: a result whose title contains all keyword terms passes; a result whose description (not title) contains all terms passes.
  - Happy path: a result matching neither title nor description is dropped from the final `results`.
  - Edge case: a result with `description_text=None` is still evaluated (and can pass) on title alone (covers KTD4).
  - Edge case: an empty/whitespace-only keyword string passes every result through unfiltered.
  - Integration: a source whose raw offers are entirely filtered out still reports `SourceStatus(status="ok")` (covers KTD5) — not re-labeled by the filter.
  - Integration: the fallback scraper still fires when raw `arbeitsagentur_results` is empty, even when another source's results are all subsequently filtered out (covers KTD6).
  - Integration: results reached via the invalid-`fallback_url` branch are filtered identically to results reached via the fallback-scrape branch (covers KTD7 — both branches converge on one filter call before the single `return`).
- **Verification:** `pytest` (full run from `backend/`) passes; a code read confirms `search()` has one filter call and one `return JobSearchResponse(...)` site, not a filter call duplicated across branches.

### U4. Remove Arbeitnow's private per-source filter, preserving location filtering

- **Goal:** Delete the keyword-matching half of Arbeitnow's `_matches` (superseded by U3's shared filter) while explicitly preserving its location-substring filtering.
- **Requirements:** R8
- **Dependencies:** U3 (the shared filter must exist before Arbeitnow's private keyword filter can be safely removed)
- **Files:**
  - `backend/app/services/job_sources/arbeitnow.py`
  - `backend/tests/services/job_sources/test_arbeitnow.py`
- **Approach:**
  1. Remove `_matches`'s keyword/title/description/company_name half; Arbeitnow's `search()` goes back to a plain fetch-and-map for keywords (R8).
  2. Keep a small standalone `location_term` substring check in `search()`'s per-item loop, unchanged in behavior (KTD9) — this is not touched by the shared filter (R6/R7 is keyword-only).
  3. Document (in a short code comment, not a new doc) that Arbeitnow results matching only via `company_name` under the old `_matches` no longer pass the new shared filter on that basis alone (KTD10) — an accepted narrowing, not a bug.
- **Patterns to follow:** N/A — this unit removes code rather than following a new pattern; the replacement behavior is U3's shared filter.
- **Test scenarios:**
  - Happy path: Arbeitnow's location-substring filtering still works standalone after `_matches`'s keyword half is removed (covers the preserved Scope Boundary; adapt `test_location_filter_is_a_case_insensitive_substring_match`).
  - Edge case: a result that previously matched only via `company_name` (not title/description) is no longer kept by Arbeitnow's client-local logic — it now relies solely on U3's shared filter, which doesn't check `company_name` (documents KTD10; replace `test_keyword_matches_against_description_and_company_too` with a test asserting the narrowed behavior).
  - Removed: `test_keyword_filter_requires_every_term_to_match` is now redundant with U3's shared-filter tests and should be deleted rather than duplicated.
- **Verification:** `pytest backend/tests/services/job_sources/test_arbeitnow.py` and the full `pytest` run pass; `grep -n "_matches" backend/app/services/job_sources/arbeitnow.py` shows no remaining keyword-matching code.

---

## Verification Contract

| Check | Command | Applies to |
|---|---|---|
| Backend test suite | `pytest` (run from `backend/`; config at `backend/pytest.ini`, `testpaths = tests`) | U1, U2, U3, U4 |
| No dangling references | `grep -rn "adzuna\|jooble" backend/app` shows the restored clients wired in, not stray removal-era comments | U1, U2 |
| Single filter/return site | Code read confirms every path out of `JobSearchService.search()` applies the filter exactly once before constructing `JobSearchResponse` | U3 |
| No credential in chained tracebacks | `caplog`-based tests (U1, U2) confirm `raise ... from None` suppresses the original exception in the orchestrator's `logger.exception()` output | U1, U2 |

No frontend test run is required — R9 is already satisfied (`source-label.util.ts` needs no change), and no other frontend file is touched by this plan.

---

## Definition of Done

- U1: `AdzunaJobsClient` restored, credential-gated via `CooldownMixin`, registered when enabled and configured; `pytest` is green.
- U2: `JoobleJobsClient` restored, same posture, with its URL-path credential never logged; `pytest` is green.
- U3: The shared relevance filter is implemented and applied exactly once on every path out of `search()`; per-source status and the fallback trigger remain pre-filter (KTD5/KTD6); `pytest` is green.
- U4: Arbeitnow's private keyword filter is removed, its location filtering is preserved standalone, and the company-name-matching narrowing (KTD10) is documented; `pytest` is green.
- No unexpected-error `RuntimeError` in either restored client logs a credential via traceback chaining (KTD2's `from None` requirement holds).
- No exploratory or abandoned code remains (e.g., a half-adapted `CooldownMixin` swap, or a filter call duplicated across branches instead of unified per KTD7).

---

## Risks & Dependencies

- **Risk:** Adzuna's or Jooble's API shape may have drifted since their pre-removal implementations. Mitigated by the Assumptions section's live re-verification step during implementation.
- **Risk:** Dropping Arbeitnow's `company_name` matching (KTD10) could reduce visible results for a company-name-only search via that source. Accepted trade-off, not mitigated further in this plan.
- **Risk:** Per-source `SourceStatus` stays pre-filter (KTD5), so a source can report `ok` while the shared filter drops all of its results as irrelevant — only the aggregate kept/dropped log line (KTD8) surfaces this, not per-source status. Accepted trade-off (smallest-diff option), not mitigated further in this plan.
- **Risk:** The `search()` control-flow refactor (U3/KTD7) touches code already carrying several prior KTDs (inner-timeout budgeting, rate-limit status mapping) and a security guard (`validate_source_url` gating the fallback scraper). Mitigated by KTD7's explicit if/else-collapse shape (preserves the guard) and U3's test scenario confirming both branches filter identically.
- **Risk:** Both restored clients parse `.json()` on an unbounded response body — no size cap, unlike the `read_capped_body`/`fetch_with_requests(..., max_bytes=...)` mechanism `shared.py` already has for the SSRF-hardened email-lookup path. This mirrors both clients' pre-removal behavior rather than introducing a new regression, but restoring them re-introduces it. Accepted as a low-severity residual risk given both are trusted, credentialed, first-party APIs rather than open scrape targets — revisit if either client should adopt `read_capped_body`.
- **Dependency:** None beyond existing settings-based credentials for Adzuna/Jooble — no shared infrastructure, no Google account (dropped from scope).

---

## Open Questions

- **Deferred to Implementation:** Whether Adzuna's or Jooble's own server-side search does synonym or stemming matching beyond literal substrings, and if so, whether the shared filter's literal-substring check (R7) risks dropping some of their genuine results. No mitigation is planned here; noted as a residual risk to watch, not a blocker.
