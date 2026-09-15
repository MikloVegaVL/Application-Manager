---
title: Job Search Source Consolidation - Plan
type: feat
date: 2026-09-15
topic: job-search-source-consolidation
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Job Search Source Consolidation - Plan

## Goal Capsule

- **Objective:** Remove Adzuna, Jooble, and Kimeta as job search sources and add Arbeitnow as their open-API replacement, favoring fewer/easier-to-maintain sources over exact coverage parity.
- **Product authority:** Scope confirmed with the user via `ce-brainstorm` dialogue on 2026-09-15. Recipient-email discovery (the other half of the original request) is not active scope here — see How This Work Fits Together.
- **Open blockers:** None. The dedup question is resolved in Planning Contract (KTD5); one item remains Deferred to Implementation (see Open Questions).

## Product Contract

### Summary

Remove Adzuna, Jooble, and Kimeta from the job search source lineup and add Arbeitnow — a free, keyless job-board API covering the German/EU market — as their sole replacement. The change trades exact coverage parity for fewer sources to maintain.

### Problem Frame

The current lineup carries eleven sources, several of which need managed API keys (Adzuna, Jooble) or scraped HTML boards (Kimeta). None of that is a data-quality complaint — it's ongoing maintenance surface: credentials to keep valid, scrapers to keep working against markup changes. Consolidating around fewer, structurally simpler sources reduces that surface without requiring the replacement to match prior result volume exactly.

### Requirements

**Removal**

- R1. Remove Adzuna as a job search source: delete `AdzunaJobsClient`, its settings-based credentials (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`), and its enable flag (`JOB_SEARCH_ADZUNA_ENABLED`).
- R2. Remove Jooble as a job search source: delete `JoobleJobsClient`, its settings-based credential (`JOOBLE_API_KEY`), and its enable flag (`JOB_SEARCH_JOOBLE_ENABLED`).
- R3. Remove Kimeta as a job search source: delete its `BoardDescriptor` entry from the board registry and its enable flag (`JOB_SEARCH_KIMETA_ENABLED`).

**Addition**

- R4. Add Arbeitnow as a new job search source, implementing the standard `SOURCE_PLATFORM` + `search()` contract. It requires no user-managed API key or settings-based credential, matching how Arbeitsagentur is integrated today.
- R5. Arbeitnow participates in the existing search fan-out and graceful-degradation behavior (unavailable sources don't fail the overall search) the same way every other source does — no source-specific exception.

**Historical data**

- R6. The source-label map keeps its `adzuna`, `jooble`, and `kimeta` entries after the corresponding clients are removed, so historical Applications and SentEmail records sourced from them keep a readable label instead of falling back to the raw platform string.

### Key Decisions

- **Add exactly one new source (Arbeitnow) rather than a 1:1 replacement for the three removed.** (session-settled: user-directed — chosen over matching prior source count/volume: the user prioritized fewer, cleaner sources over coverage parity.) Governs R4, R5.
- **Arbeitnow chosen over EURES, Interamt/Bund.de, and paid aggregators (Fantastic.jobs, Jobspipe, TheirStack).** EURES API access is restricted to certified partner organizations; Interamt/Bund.de has no public API; the others require paid keys. None meet the "open like Arbeitsagentur" bar Arbeitnow does. Governs R4.
- **This overhaul only touches Adzuna, Jooble, and Kimeta.** (session-settled: user-directed) The existing scraper-based boards (StepStone, Indeed, GermanTechJobs, Programmiererjobboerse, devjobs) and LinkedIn/Xing are unaffected. Governs Scope Boundaries.
- **Historical source labels are preserved, not left to fall back to raw strings.** (session-settled: user-directed) Governs R6.

### Scope Boundaries

- Existing scraper-based boards (StepStone, Indeed, GermanTechJobs, Programmiererjobboerse, devjobs) and the LinkedIn/Xing integrations are untouched — not replaced or re-evaluated here.
- No broader "replace all scrapers with open APIs" initiative — scope is limited to the three named removals.
- No international source expansion — Germany/EU (Arbeitnow's existing coverage) is the only market considered.
- Recipient-email discovery via company name + address is a separate, independently deliverable outcome, not part of this plan.

<!-- ce-section: work-relationships -->
### How This Work Fits Together

This plan owns the job-source overhaul: removing Adzuna/Jooble/Kimeta and adding Arbeitnow. The original request also named a second outcome, which the user chose to keep out of this plan. This breakdown is the current understanding, not a committed roadmap:

- Recipient-email discovery fallback (search by company name + address when a job posting has no extractable email) — Can proceed independently of this plan. Not yet its own brainstorm.

### Sources / Research

- `backend/app/services/job_search_service.py:70-73` — the `SourceRegistration` contract (`SOURCE_PLATFORM` + `search()`) every source implements.
- `backend/app/services/job_sources/boards.py:63-94` — board registry, including the `kimeta` `BoardDescriptor` entry to remove.
- `backend/app/services/job_sources/adzuna.py:37-52`, `backend/app/services/job_sources/jooble.py:44-49` — clients to remove.
- `backend/app/core/config.py:111-125` — settings flags and credentials to remove (`JOB_SEARCH_ADZUNA_ENABLED`, `JOB_SEARCH_JOOBLE_ENABLED`, `JOB_SEARCH_KIMETA_ENABLED`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`).
- `backend/app/services/job_search_service.py:84-110` — `ArbeitsagenturJobsClient`, the existing open-API integration Arbeitnow's integration should mirror (no settings-based credential, unconditional registration).
- `frontend/src/app/core/utils/source-label.util.ts` — the source label map R6 requires to stay unchanged.
- [Arbeitnow Job Board API](https://www.arbeitnow.com/blog/job-board-api) — confirms no API key required; Europe endpoint `https://www.arbeitnow.com/api/job-board-api`; sourced from ATS platforms including Personio, Greenhouse, SmartRecruiters, Lever. Documents only `remote` and `visa_sponsorship` query filters — no server-side keyword or location search.
- Live call to `https://www.arbeitnow.com/api/job-board-api` (2026-09-15) — confirmed response field names: `slug`, `company_name`, `title`, `description`, `remote`, `url`, `tags`, `job_types`, `location`, `created_at`. Pagination envelope (`links`/`meta`) not observed in the sampled response; treat as unconfirmed (see Open Questions).
- [EURES European Job Mobility Portal](https://eures.europa.eu/index_en) — API access restricted to certified EURES partner organizations, ruled out as not genuinely open.
- `backend/app/services/job_search_service.py` (`JobSearchService.search()` fan-out loop) — confirmed no cross-source deduplication exists anywhere today (`results.extend(offers)` per source, no uniqueness check by URL or title+company).
- `docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md` (KD9, Scope Boundaries) — dedup was explicitly deferred when the current 13-source lineup was built, with a specific note that Kimeta (a meta-search engine aggregating other boards) makes duplicates "materially more likely."
- `docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md` (Scope Boundaries) — dedup was already deferred once before that, when LinkedIn/Xing were added.
- `backend/app/services/job_sources/shared.py` — `CooldownMixin` (reused by U2) and `redact_credentials()` (candidate for removal in U1 only if unused; Jooble's docstring notes its URL-path credential was never caught by this regex, but `shared.py`'s own `_safe_error_text()` also calls it, so it likely remains in use).
- `backend/tests/services/job_sources/test_adzuna.py` — test structure (requests_mock, cooldown reset in setup/teardown) that `test_arbeitnow.py` should mirror.

---

## Planning Contract

**Product Contract preservation:** unchanged. Requirements R1-R6 and Key Decisions carry forward verbatim from the `ce-brainstorm` version; this enrichment only adds implementation-facing sections below.

### Key Technical Decisions

- KTD1. **`ArbeitnowJobsClient` lives in its own module, `backend/app/services/job_sources/arbeitnow.py`**, not inlined into `job_search_service.py`. Matches the existing per-source-module pattern (`adzuna.py`, `jooble.py`) and keeps the one-way dependency rule intact: `job_sources/` modules never import `job_search_service.py`. Governs U2.
- KTD2. **No settings-based enable flag and no credential for Arbeitnow; registration is unconditional.** (session-settled: user-approved — chosen over gating it behind a flag like every board/API source: origin Requirement R4 specifies no user-managed API key or settings-based credential, matching how Arbeitsagentur is integrated, which itself has no flag.) Governs R4, U2.
- KTD3. **The Arbeitnow client filters by `keywords` and `location` client-side after fetching results.** Arbeitnow's documented query parameters are only `remote` and `visa_sponsorship` — no server-side keyword or location search exists to call into. This mirrors how the existing HTML board sources already filter fetched listings client-side. Governs U2.
- KTD4. **The Arbeitnow client reuses `CooldownMixin`** to back off on HTTP 429, even though it needs no API key. A public, keyless API can still rate-limit; Adzuna and Jooble already establish this pattern for external job-API clients. Governs U2.
- KTD5. **Cross-source deduplication stays out of scope**, continuing the posture set by two prior plans. `docs/plans/2026-08-12-...-external-platforms-plan.md` and `docs/plans/2026-09-11-...-broader-source-coverage-plan.md` (KD9) both explicitly deferred dedup; the latter specifically flagged Kimeta — a meta-search engine aggregating other boards — as the source most likely to cause duplicates. This plan removes Kimeta, net-reducing duplicate risk rather than adding it. No dedup infrastructure exists today to hook into (`JobSearchService.search()`'s fan-out loop does a plain `results.extend(offers)` per source). Governs Scope Boundaries.
- KTD6. **Prune `shared.py`'s `redact_credentials()` only if the U1 grep confirms no remaining caller.** Jooble never called it — its credential lives in the URL path, not the query string. `shared.py`'s own `_safe_error_text()` also calls it internally, so it likely stays in use by every source that goes through the shared fetch helpers, not just Adzuna — do not assume removal without the grep. Governs U1.

### Assumptions

- Arbeitnow's response field names (`slug`, `company_name`, `title`, `description`, `remote`, `url`, `tags`, `job_types`, `location`, `created_at`) hold as observed in the 2026-09-15 live call. The pagination envelope (whether a `links`/`meta` section exists) was not observed in the sampled response and needs a live re-check before U2 is implemented — see Open Questions.
- Arbeitnow's API remains keyless and unauthenticated at implementation time, consistent with its own documentation and the existing Arbeitsagentur precedent.

---

## Implementation Units

### U1. Remove Adzuna, Jooble, and Kimeta job search sources

- **Goal:** Delete the three sources' clients, registry entries, credentials, and settings flags; leave their frontend labels untouched.
- **Requirements:** R1, R2, R3, R6 (R6 is a non-change constraint on this unit — do not touch the label map)
- **Dependencies:** None
- **Files:**
  - `backend/app/services/job_sources/adzuna.py` (delete)
  - `backend/app/services/job_sources/jooble.py` (delete)
  - `backend/app/services/job_sources/boards.py` (remove the `kimeta` `BoardDescriptor` entry from `BOARD_DESCRIPTORS`)
  - `backend/app/core/config.py` (remove `JOB_SEARCH_ADZUNA_ENABLED`, `JOB_SEARCH_JOOBLE_ENABLED`, `JOB_SEARCH_KIMETA_ENABLED`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`)
  - `backend/app/services/job_search_service.py` (remove `AdzunaJobsClient`/`JoobleJobsClient` imports; remove `"adzuna"`/`"jooble"`/`"kimeta"` from the `source_enabled` dict; remove the `adzuna_app_id`/`adzuna_app_key`/`jooble_api_key` locals and both registration blocks in `_build_default_registry()`)
  - `backend/app/services/job_sources/shared.py` (remove `redact_credentials()` only if KTD6's grep check confirms no remaining caller)
  - `backend/app/main.py` (update the urllib3 DEBUG-log-suppression comment that names Adzuna/Jooble specifically)
  - `backend/tests/services/job_sources/test_adzuna.py` (delete)
  - `backend/tests/services/job_sources/test_jooble.py` (delete)
  - `backend/tests/services/test_job_search_service.py` (update `_NEW_SOURCE_FLAGS`, `test_default_registry_is_built_from_settings_without_injection`, `test_api_credentials_default_to_empty_strings`, `test_source_status_accepts_not_configured_reason`)
  - `backend/tests/services/job_sources/test_boards.py` (remove `"kimeta"` from `BOARD_KEYS` and `JOB_SEARCH_KIMETA_ENABLED` from `BOARD_FLAGS`; update the board-count assertions from 5 to 4)
  - `backend/.env.example` (remove the `JOB_SEARCH_KIMETA_ENABLED`/`JOB_SEARCH_ADZUNA_ENABLED`/`JOB_SEARCH_JOOBLE_ENABLED` and `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`/`JOOBLE_API_KEY` example lines)
  - `frontend/src/app/core/utils/source-label.util.ts` — no change (R6)
- **Approach:**
  1. Delete `adzuna.py`, `jooble.py`, and their test files.
  2. Remove the `kimeta` entry from `boards.py`'s `BOARD_DESCRIPTORS`.
  3. Remove the three settings flags and three credentials from `config.py`.
  4. Remove the client imports, `source_enabled` entries, and registration blocks in `job_search_service.py`'s `_build_default_registry()`.
  5. Grep the backend for other callers of `redact_credentials()` — check `shared.py`'s own `_safe_error_text()` too (KTD6) — and delete it only if none remain.
  6. Update the stale urllib3-suppression comment in `main.py`.
  7. Update the four `test_job_search_service.py` assertions that reference adzuna/jooble/kimeta as expected-present platforms.
  8. Update `test_boards.py`'s `BOARD_KEYS`/`BOARD_FLAGS` and count assertions to drop `kimeta`.
  9. Remove the now-dead Adzuna/Jooble/Kimeta example lines from `backend/.env.example`.
- **Test scenarios:**
  - Happy path: `test_default_registry_is_built_from_settings_without_injection` no longer expects `"adzuna"`/`"jooble"` in platforms or `"kimeta"` in the board loop; the allowlist set reflects the reduced source count.
  - Happy path: `test_api_credentials_default_to_empty_strings` no longer references the three deleted credential fields.
  - Happy path: `test_boards.py`'s board-count and registry assertions reflect 4 remaining boards (stepstone, germantechjobs, indeed, programmiererjobboerse), not 5.
  - Edge case: a persisted Application or SentEmail record with `source_platform="adzuna"` (or `jooble`/`kimeta`) still resolves through `sourceLabel()` to its readable label, not the raw string — covers R6.
  - Integration: the full backend suite imports cleanly with no dangling references to the deleted client modules.
- **Verification:** `pytest` (run from `backend/`) passes. `grep -rn "adzuna\|jooble\|kimeta" backend/app` returns no hits outside comments/history; `frontend/src/app/core/utils/source-label.util.ts` still contains all three label entries.

### U2. Add Arbeitnow job search source

- **Goal:** Implement `ArbeitnowJobsClient` on the standard `SOURCE_PLATFORM` + `search()` contract and register it unconditionally.
- **Requirements:** R4, R5
- **Dependencies:** None (independent of U1; sequencing after U1 keeps the `job_search_service.py` edits linear but is not a hard requirement)
- **Files:**
  - `backend/app/services/job_sources/arbeitnow.py` (new — `ArbeitnowJobsClient`)
  - `backend/app/services/job_search_service.py` (import `ArbeitnowJobsClient`; add its unconditional registration in `_build_default_registry()`, mirroring the Arbeitsagentur registration)
  - `backend/tests/services/job_sources/test_arbeitnow.py` (new)
  - `backend/tests/api/test_jobs.py` (update `_ALL_SOURCE_PLATFORMS` to drop `adzuna`/`jooble`/`kimeta` and add `arbeitnow`; update `_NOT_OK_PLATFORMS` if it references any of them)
- **Approach:**
  1. Define `ArbeitnowJobsClient` with `SOURCE_PLATFORM = "arbeitnow"` in its own module (KTD1), reusing `shared.py`'s `DEFAULT_USER_AGENT`, `validate_source_url`, `strip_html`, and `fold_salary_homeoffice` helpers.
  2. Fetch `https://www.arbeitnow.com/api/job-board-api`; confirm the live pagination envelope before finalizing (see Open Questions).
  3. Map each job object's fields onto `JobOfferCreate`: `title`, `company_name`, `url`, `location`, `tags`, `job_types`, `remote`, `created_at` directly, and `description` through `strip_html` (and `fold_salary_homeoffice` where salary/homeoffice text is present) before it becomes `description_text`, mirroring `adzuna.py`/`jooble.py`.
  4. Filter fetched results by `keywords` and `location` client-side (KTD3), since the API has no matching server-side query params.
  5. Wrap the HTTP call with `CooldownMixin`, backing off on HTTP 429 (KTD4).
  6. Register unconditionally in `_build_default_registry()`: no `is_configured()` method, no settings flag (KTD2).
  7. Update `test_jobs.py`'s hardcoded platform list to reflect the new lineup (drop adzuna/jooble/kimeta, add arbeitnow).
- **Test scenarios:**
  - Happy path: `search("python", "Berlin")` returns mapped `JobOfferCreate` objects for matching sample listings (requests_mock fixture with 2-3 jobs).
  - Happy path: a listing with `remote=true` and `location="Homeoffice"` maps without a location-filtering false negative.
  - Edge case: zero results after client-side filtering returns an empty list, not an error.
  - Edge case: a listing missing an optional field (e.g., empty `tags`) still maps without raising.
  - Edge case: a `description` containing raw HTML tags maps to a stripped `description_text`, matching the existing `adzuna.py`/`jooble.py` behavior.
  - Error path: HTTP 429 triggers `CooldownMixin`'s backoff, matching the existing Adzuna/Jooble cooldown test pattern.
  - Error path: HTTP 5xx or a network failure maps to `status="unavailable"` via the existing orchestrator error path, not an unhandled exception.
  - Integration: `_build_default_registry()` includes `arbeitnow` in its default platform set unconditionally, mirroring the existing `arbeitsagentur` assertion in `test_default_registry_is_built_from_settings_without_injection`.
  - Integration: `test_jobs.py`'s platform-enumeration tests reflect the new source lineup.
- **Verification:** `pytest backend/tests/services/job_sources/test_arbeitnow.py` and the full `pytest` run pass. A live call to the real Arbeitnow endpoint during implementation confirms the field-mapping and pagination assumptions in Approach steps 2-3.

---

## Verification Contract

- Backend: `pytest` (run from `backend/`; config at `backend/pytest.ini`, `testpaths = tests`). Proves both units — U1's removal leaves no dangling references and U2's addition is covered by `test_arbeitnow.py`.
- No frontend test run is required — R6 requires `frontend/src/app/core/utils/source-label.util.ts` to stay unchanged, and no other frontend file is touched.

---

## Definition of Done

- U1: Adzuna/Jooble/Kimeta clients, settings flags, credentials, and registrations are deleted; `pytest` is green; the frontend label map is untouched.
- U2: `ArbeitnowJobsClient` is implemented, registered unconditionally, and covered by `test_arbeitnow.py`; `pytest` is green.
- The live Arbeitnow API call (Assumptions, Open Questions) has been re-verified during implementation, and `_map_offer`/pagination logic matches the real response shape.
- No exploratory or abandoned code remains (e.g., a partially-removed `redact_credentials()` or a half-written Arbeitnow client from an earlier approach).

---

## Risks & Dependencies

- **Risk:** Arbeitnow's API is documented only via a blog post, not a formal spec — pagination or field shape could differ from the 2026-09-15 sample. Mitigated by the Open Questions live-verification step and by KTD3's client-side filtering, which doesn't depend on undocumented query parameters.
- **Risk:** Removing `redact_credentials()` (KTD6) could break an undiscovered caller. Mitigated by U1's grep-before-delete step.
- **Risk:** Arbeitnow aggregates postings from many unaudited ATS posters (Personio, Greenhouse, SmartRecruiters, Lever), not a single vetted employer feed like Arbeitsagentur. The app already auto-fills the application send-to address from `description_text` via `extractEmail()`, with no check that the extracted address matches the poster's domain — a risk that predates this plan (every existing source already flows through the same extraction) but that Arbeitnow's broader, multi-tenant sourcing modestly widens. Full mitigation (e.g., domain cross-checking) is out of scope here; it belongs to the deferred recipient-email discovery follow-up (How This Work Fits Together), which is the natural place to also harden this existing auto-fill.
- **Dependency:** None beyond the public Arbeitnow endpoint — no key or account to provision, consistent with R4.

---

## Open Questions

- **Deferred to Implementation:** Arbeitnow's exact pagination envelope (whether a `links`/`meta` section exists, how many pages a search should fetch) wasn't confirmed by available documentation or the single sampled call. Verify with a live call, and confirm the chosen page count fits the existing per-source `inner_timeout` budget, before finalizing U2's fetch/pagination logic.
- **Deferred to Implementation:** Confirm that the untrusted-`description_text` mitigation already used for the AI cover-letter generation prompt path (per `docs/plans/2026-09-11-...-broader-source-coverage-plan.md`) applies transparently to Arbeitnow-sourced descriptions, with no per-source bypass.
