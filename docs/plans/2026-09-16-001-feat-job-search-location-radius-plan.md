---
title: Job Search Location Radius - Plan
type: feat
date: 2026-09-16
topic: job-search-location-radius
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Job Search Location Radius - Plan

## Goal Capsule

- **Objective:** Add a radius option to job search so a location search also surfaces jobs in nearby towns, not just exact string matches.
- **Product authority:** This plan.
- **Open blockers:** None.
- **Execution profile:** Standard. Three implementation units, sequential (U1 -> U2, U3 depends only on U1).
- **Tail ownership:** `ce-work` (or an equivalent executor) owns implementation, tests, and commit; this plan makes no code changes.

## Product Contract

**Product Contract preservation:** unchanged, except the Outstanding Question below is resolved into Planning Contract KTD2/KTD3 and removed here rather than left stale.

### Summary

Add a Radius control next to Location on job search, as a preset km dropdown. It's sent to the sources whose APIs support geo-radius search (Arbeitsagentur, Adzuna, Jooble); sources without that capability keep matching on the typed location text as they do today. Radius widens the result set — it never narrows it.

### Requirements

**Search input**

- R1. The job search form gains a Radius control next to Location, rendered as a preset dropdown with km steps up to 200km (e.g. 5/10/25/50/100/200).
- R2. The Radius control is disabled whenever Location is empty — a radius has no center point to measure from without one.
- R3. Leaving Radius unset preserves today's behavior: every source matches on the location text exactly as it does now, with no radius applied.

**Result composition**

- R4. When a radius is selected, only the sources whose API accepts a radius parameter (Arbeitsagentur, Adzuna, Jooble) apply it; the remaining sources keep searching by the typed location text unfiltered.
- R5. Radius-filtered and unfiltered results are shown together in one list, as today — selecting a radius only adds matches, it never removes results from a non-radius source.

### Key Decisions

- **Non-radius sources stay included and unfiltered, rather than excluded while a radius is set.** Keeps result volume up; the tradeoff is that not every card is guaranteed to sit within the chosen radius. Governs R4, R5. (session-settled: user-directed — chosen over excluding those sources entirely while a radius is active: more results matters more here than guaranteed radius accuracy on every card.)
- **Preset dropdown, not a slider or free-number input.** Matches how the underlying source APIs already work and avoids introducing a new control pattern into the app. Governs R1. (session-settled: user-directed — chosen over a slider or free-number input.)
- **Radius disabled without a Location value, rather than allowed and silently ignored.** Prevents a selection that has no meaning yet. Governs R2. (session-settled: user-directed.)
- **No radius selected keeps exact location-string matching as the default.** Radius is additive, not a replacement for the existing behavior. Governs R3.

### Acceptance Examples

- AE1. **Covers R2.** Given the Location field is empty, when the user opens job search, then the Radius dropdown is disabled.
- AE2. **Covers R1, R4, R5.** Given Location is "Berlin" and Radius is set to 50km, when the user searches, then Arbeitsagentur/Adzuna/Jooble return jobs within their own interpretation of ~50km of Berlin, while LinkedIn/Xing/Arbeitnow/Devjobs/generic boards return their normal text-matched results for "Berlin", and both sets appear together.
- AE3. **Covers R3.** Given Location is "Berlin" and Radius is left unset, when the user searches, then every source behaves exactly as it does today (no radius parameter sent to any source).

### Scope Boundaries

- Browser "use my location" auto-fill for the Location field — not requested, deferred.
- Client-side distance filtering or geocoding to give non-radius sources approximate radius support — rejected in favor of the "include unfiltered" decision above.
- Miles/imperial units — out of scope; the app and its sources are Germany-focused, so radius is km only.

### Sources / Research

- `backend/app/api/jobs.py:28-57` — current `/jobs/search` endpoint; `location` is the only geo query param today.
- `backend/app/services/job_search_service.py:424-473` — `JobSearchService.search()` fans out to every registered source through one uniform call, `executor.submit(registration.client.search, keywords, location)` (line 470); every source client shares the `search(keywords, location)` contract (`SourceRegistration` docstring, line 67-75).
- `backend/app/services/job_search_service.py:126-135` — `ArbeitsagenturJobsClient.search()` sends `wo` (location) only; no `umkreis` (radius) param sent today.
- `backend/app/services/job_sources/adzuna.py:78-106` — `AdzunaJobsClient.search()` sends `where` (location) only; no `distanceKm` param sent today.
- `backend/app/services/job_sources/jooble.py:85-111` — `JoobleJobsClient.search()` POSTs a JSON body with `location` only; no `radius` param sent today.
- `backend/app/services/job_sources/linkedin.py`, `xing.py`, `arbeitnow.py`, `devjobs.py`, `shared.py:715-733` (`BoardSourceAdapter`, used by the generic named-board sources) — no radius parameter exists; LinkedIn's geo scope is fixed to Germany via a static `geoId` regardless of `location`, and Arbeitnow has no server-side location filter at all (client-side substring match only).
- Confirmed externally (not yet used in this codebase): Bundesagentur für Arbeit Jobsuche API `umkreis` param, km, accepts values at least up to 200 — [bundesAPI/jobsuche-api](https://github.com/bundesAPI/jobsuche-api); Adzuna API `distanceKm` param; Jooble REST API `radius` param, allowed values `0, 4, 8, 16, 26, 40, 80` — [Jooble REST API docs](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation).
- `frontend/src/app/core/services/job-search-state.service.ts:29-30` — `location`/`keywords` are plain `signal('')` state, persisted across navigation; the new radius state mirrors this.
- `frontend/src/app/pages/job-search/job-search.component.ts:50-53` — `searchForm` is a `formBuilder.nonNullable.group` with string controls (`keywords`, `location`); no existing `mat-select` control in this component to mirror, but the app uses Angular Material throughout.
- `backend/tests/api/test_jobs.py`, `backend/tests/services/test_job_search_service.py`, `backend/tests/services/job_sources/test_adzuna.py`, `backend/tests/services/job_sources/test_jooble.py`, `frontend/src/app/core/services/job.service.spec.ts`, `frontend/src/app/pages/job-search/job-search.component.spec.ts` — existing test files to extend, not create.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Extend the shared `search(keywords, location)` contract to `search(keywords, location, radius_km=None)` on every registered source client**, not only the three that use it, and **switch the orchestrator's fan-out dispatch from positional to keyword arguments** (`registration.client.search(keywords=keywords, location=location, radius_km=radius_km)`). `ArbeitsagenturJobsClient.search` already has a third positional parameter, `results_limit: int = 25` (`job_search_service.py:126-131`) — appending `radius_km` positionally would silently bind the chosen radius into `results_limit` instead, so the fan-out must dispatch by keyword to make parameter order irrelevant. Sources that can't act on radius simply ignore the `radius_km` keyword. Governs R4. `Files:` `backend/app/services/job_sources/linkedin.py`, `xing.py`, `arbeitnow.py`, `devjobs.py`, `shared.py`.
- KTD2. **Round a UI-selected radius up to the nearest value a target source's API accepts, never down, capped at that source's maximum.** Jooble only accepts `4/8/16/26/40/80` km; rounding up (e.g. UI `50` -> Jooble `80`) keeps the "radius only adds results, never narrows them" bias from the Product Contract's Key Decisions. Arbeitsagentur and Adzuna accept the UI value unchanged (no documented discrete-step limitation). Governs R4.
- KTD3. **UI radius presets: `5, 10, 25, 50, 100, 200` km.** Spans the full "up to 200km" range from the Product Contract in a small set of round numbers; interacts predictably with KTD2's Jooble rounding (`5→8, 10→16, 25→26, 50→80, 100→80, 200→80`). Governs R1.
- KTD4. **The frontend radius control's "unset" state is an empty string (`''`), not `null`.** Mirrors the existing `location` control's default-empty-string pattern (`job-search.component.ts:50-53`) so the form stays uniformly string-typed. Governs R1, R3.
- KTD5. **The backend, not the frontend, is the single source of truth for "no Location means no radius."** `JobSearchService.search()` clears `radius_km` before dispatch whenever `location` is empty (R3), so a frontend edge case (e.g. clearing Location after picking a radius, then submitting) can't leak a radius through — Angular's `getRawValue()` still returns a disabled control's value, so the frontend must not be trusted alone for this invariant. Governs R2, R3.

### Implementation Constraints

- Every source client's `search()` signature changes (KTD1) — even the five clients that ignore the new parameter — because the orchestrator calls all of them in one loop. Missing any one of them breaks that loop with a `TypeError`, so U1 must land as a single unit across all client files.
- `ArbeitsagenturJobsClient.search` keeps its existing `results_limit: int = 25` parameter untouched; KTD1's keyword-based dispatch means `radius_km` binds by name regardless of where it's added in that signature.
- No persisted schema or response-model change: radius is a search-time filter, not stored on `JobOffer` or in `JobSearchResponse`.

### Risks & Dependencies

- Adzuna's and Arbeitsagentur's exact accepted radius range beyond the documented examples (`umkreis=200`, Adzuna's default-5-mile framing) is unverified against live traffic — an out-of-range value's actual server-side behavior (clamp vs. reject vs. ignore) is discovered at implementation/test time, not assumed here.

---

## Implementation Units

### U1. Thread `radius_km` through the API and orchestrator; extend every source client's signature

**Goal:** Make `radius_km` flow from the search endpoint to every registered source client without changing any source's behavior yet.

**Requirements:** R2, R3, R4 (plumbing only — KTD1, KTD5)

**Dependencies:** None.

**Files:**
- `backend/app/api/jobs.py`
- `backend/app/services/job_search_service.py`
- `backend/app/services/job_sources/linkedin.py`
- `backend/app/services/job_sources/xing.py`
- `backend/app/services/job_sources/arbeitnow.py`
- `backend/app/services/job_sources/devjobs.py`
- `backend/app/services/job_sources/shared.py`
- `backend/tests/api/test_jobs.py`
- `backend/tests/services/test_job_search_service.py`

**Approach:**
- Add `radius_km: int | None = Query(default=None, ge=1, le=200, description="Umkreis in km")` to `search_jobs` in `jobs.py`; pass it to `service.search(radius_km=radius_km)`.
- In `JobSearchService.search()` (`job_search_service.py:424`), accept `radius_km: int | None = None`. Before dispatch, apply KTD5: `if not location: radius_km = None`. Switch the existing `executor.submit(registration.client.search, keywords, location)` call (line 470) to keyword arguments: `executor.submit(registration.client.search, keywords=keywords, location=location, radius_km=radius_km)` (KTD1 — avoids colliding with `ArbeitsagenturJobsClient`'s existing `results_limit` positional parameter).
- Add `radius_km: int | None = None` to the `search()` signature of `LinkedInJobsClient`, `XingJobScraper`, `ArbeitnowJobsClient`, `DevjobsScraper`, and `BoardSourceAdapter` (`shared.py`) — accepted and intentionally unused (KTD1).

**Patterns to follow:** The existing `location: str | None = None` parameter on every one of these `search()` methods — same optional-keyword shape, just one more parameter.

**Test scenarios:**
- Happy path: `GET /jobs/search?keywords=Engineer&location=Berlin&radius_km=50` returns 200.
- Edge case: `radius_km=50` with no `location` — `JobSearchService.search()` forwards `radius_km=None` to every client (R2/R3, KTD5).
- Edge case: `radius_km=0` and `radius_km=500` — API rejects both with 422 (`ge=1, le=200`).
- Integration: with a stub registry covering all source types (radius-aware and not), `JobSearchService.search()` completes without a `TypeError` from the new `radius_km` keyword argument.
- Regression: `ArbeitsagenturJobsClient`'s existing `results_limit`/`size` request param is unchanged when `radius_km` is set (guards against the keyword-dispatch fix in KTD1).

**Verification:** `cd backend && pytest tests/api/test_jobs.py tests/services/test_job_search_service.py` passes; no other source test file's assertions on request shape change.

---

### U2. Apply radius on the three capable sources (Arbeitsagentur, Adzuna, Jooble)

**Goal:** Make radius actually narrow-to-widen results on the three sources whose APIs support it.

**Requirements:** R4 (KTD2)

**Dependencies:** U1.

**Files:**
- `backend/app/services/job_search_service.py` (`ArbeitsagenturJobsClient.search`)
- `backend/app/services/job_sources/adzuna.py`
- `backend/app/services/job_sources/jooble.py`
- `backend/tests/services/test_job_search_service.py`
- `backend/tests/services/job_sources/test_adzuna.py`
- `backend/tests/services/job_sources/test_jooble.py`

**Approach:**
- `ArbeitsagenturJobsClient.search`: add `radius_km` param; when both `location` and `radius_km` are set, add `params["umkreis"] = radius_km` (no snapping — KTD2).
- `AdzunaJobsClient.search`: add `radius_km` param; when both are set, add `params["distanceKm"] = radius_km` (no snapping).
- `JoobleJobsClient.search`: add `radius_km` param. When both are set, snap it up to the nearest value in `[4, 8, 16, 26, 40, 80]` (cap at `80`) via a small local helper function, then set `payload["radius"] = str(snapped_value)`.

**Patterns to follow:** The existing `if location: params["where"] = location` (Adzuna) / `if location: params["wo"] = location` (Arbeitsagentur) conditional-add style already in each client.

**Test scenarios:**
- Happy path: Arbeitsagentur, `location="Berlin", radius_km=50` -> request includes `umkreis=50`.
- Happy path: Adzuna, `location="Berlin", radius_km=25` -> request includes `distanceKm=25`.
- Happy path (parametrized): Jooble snapping table — `5→8`, `10→16`, `25→26`, `50→80`, `100→80`, `200→80`.
- Edge case: `radius_km` set but `location` empty -> none of the three send a radius parameter (mirrors R2/KTD5 — this exercises each client directly, independent of the orchestrator-level guard in U1).
- Edge case: `radius_km=None` (unset) -> outgoing request is byte-identical to today's (regression coverage for R3).

**Verification:** `cd backend && pytest tests/services/test_job_search_service.py tests/services/job_sources/test_adzuna.py tests/services/job_sources/test_jooble.py` passes.

---

### U3. Frontend: Radius control on job search

**Goal:** Let the user pick a radius next to Location, disabled until Location has a value, and send it to the backend.

**Requirements:** R1, R2, R3 (KTD3, KTD4)

**Dependencies:** U1 (the `radius_km` query param must exist for the frontend to call).

**Files:**
- `frontend/src/app/core/services/job.service.ts`
- `frontend/src/app/core/services/job.service.spec.ts`
- `frontend/src/app/core/services/job-search-state.service.ts`
- `frontend/src/app/core/services/job-search-state.service.spec.ts`
- `frontend/src/app/pages/job-search/job-search.component.ts`
- `frontend/src/app/pages/job-search/job-search.component.html`
- `frontend/src/app/pages/job-search/job-search.component.spec.ts`

**Approach:**
- `JobSearchStateService`: add `readonly radiusKm = signal('')`, alongside `location`, following the same persist-across-navigation pattern.
- `JobService.searchJobs`: add an optional `radiusKm?: string` parameter; when non-empty, add it to `HttpParams` as `radius_km`.
- `JobSearchComponent.searchForm`: add a `radiusKm: ['']` control (KTD4). Add a `mat-select` next to the Location `mat-form-field` in the template, with options `5/10/25/50/100/200` (KTD3), matching the existing outline appearance and `mat-icon matPrefix` convention.
- Disable the radius control whenever Location's raw value is empty, and enable it otherwise: set the initial disabled state from the form's starting `location` value, and subscribe to `location.valueChanges` to toggle it as the user types (R2).
- Add a `mat-hint` (or equivalent `aria-describedby` text) on the radius field, shown while it's disabled, explaining why (e.g. "Add a location to set a search radius") — a disabled control with no stated reason is a dead end for sighted and screen-reader users alike.
- `onSearch()`: read `radiusKm` from `getRawValue()`, pass it to `jobService.searchJobs(...)`, and persist it to `state.radiusKm`. Do not add a duplicate "clear radius if location is empty" guard here — KTD5 makes the backend the authoritative guard against a stale disabled value.

**Patterns to follow:** `job-search.component.ts:50-53` (`searchForm` construction), the existing `location` `mat-form-field` block in `job-search.component.html` for markup/styling conventions.

**Test scenarios:**
- Happy path: Location filled, a radius chosen, submit -> `JobService.searchJobs` is called with the chosen `radius_km`.
- Edge case: Location empty on load -> the radius control starts disabled and shows the explanatory hint.
- Edge case: user types into an initially-empty Location -> the radius control becomes enabled.
- Edge case: user clears a filled Location -> the radius control becomes disabled again.
- Edge case: Location and Radius both empty, submit -> `JobService.searchJobs` is called without a `radius_km` param (unchanged request shape, R3).

**Verification:** `cd frontend && ng test --watch=false` covering the three files above passes.

---

## Verification Contract

| Command | Scope |
|---|---|
| `cd backend && pytest tests/api/test_jobs.py tests/services/test_job_search_service.py tests/services/job_sources/test_adzuna.py tests/services/job_sources/test_jooble.py` | U1, U2 |
| `cd backend && pytest` | Full backend regression — confirms U1's signature change didn't break the untouched-behavior clients (LinkedIn, Xing, Arbeitnow, Devjobs, generic boards) |
| `cd frontend && ng test --watch=false` | U3, plus full frontend regression |

## Definition of Done

- U1, U2, and U3 implemented; a radius selected in the UI reaches Arbeitsagentur, Adzuna, and Jooble, and every other source keeps searching by location text only.
- All Verification Contract commands pass.
- Leaving Radius unset produces byte-identical outgoing requests to every source, compared to before this plan (R3 regression check, covered by U1/U2 test scenarios).
- No exploratory or dead-end code left in the diff.
