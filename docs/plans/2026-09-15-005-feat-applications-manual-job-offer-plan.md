---
title: Manual Job Offer Entry - Plan
type: feat
date: 2026-09-15
topic: applications-manual-job-offer
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Manual Job Offer Entry - Plan

## Goal Capsule

- **Objective:** Let the user add a directly-found job offer from the Applications page and generate an application from it through the existing editor, without going through job search scraping.
- **Product authority:** This brainstorm (`ce-brainstorm`). Single coherent work unit — no surrounding work was split out.
- **Open blockers:** None.

---

## Product Contract

### Summary

A dialog on the Applications page lets the user manually enter a directly-found job offer and jump straight into the application editor to generate a cover letter for it, reusing the existing job-save and draft-application infrastructure end to end.

### Requirements

**Entry point & dialog**

- R1. The Applications page has an "Add job offer" action that opens a dialog for entering a directly-found job offer.
- R2. The dialog collects: title (required), company (required), a source/reference field (required free text — a URL if one exists, otherwise any identifying description), job description text (optional), and application email (optional).
- R3. The dialog does not collect a location field.
- R4. The saved job offer is tagged with a distinct source-platform value (e.g. `manual`) that renders under its own label (e.g. "Direct") alongside existing sources such as LinkedIn or Arbeitnow.

**Save & duplicate handling**

- R5. Submitting the dialog saves the entry through the existing job-save flow, which also creates the accompanying draft application — identical to saving a scraped search result.
- R6. If the entered source/reference matches an already-saved job offer, the dialog surfaces the conflict and offers to open the existing application instead of creating a duplicate.

**Post-save navigation**

- R7. On a successful save with no conflict, the user is taken directly into the application editor for the new job offer, which generates the cover letter automatically since none exists yet.
- R8. The new application appears as a card in the Applications list identically to any other draft application — no separate logic is needed for its list appearance.

### Key Decisions

- **Jump straight into the editor after save, rather than returning to the list first.** (session-settled: user-directed — chosen over saving and staying on the list so the user opens the new card themselves) Governs R7.
- **Reuse the existing job-save endpoint and its draft-application-on-save behavior; no manual-specific backend endpoint or schema.** (session-settled: user-approved — proposed as the approach and confirmed in the scoping synthesis) Governs R5, R8.
- **Source/reference is required free text, not a validated URL.** (session-settled: user-directed — chosen over an optional field with an auto-generated placeholder, keeping the existing duplicate check meaningful for offers with no posting link) Governs R2, R6.
- **Duplicate detection offers to open the existing application, reusing the job-search page's existing recovery pattern for the same conflict.** (session-settled: user-directed — chosen over a plain error) Governs R6.
- **Location is intentionally excluded from the manual-entry dialog**, even though scraped offers carry it. (session-settled: user-directed) Governs R3.
- **Description text stays optional, nudged only via UI copy**, even though it is what the AI reads to draft the cover letter. (session-settled: user-approved — leaving it a hint rather than a requirement) Governs R2.

### Key Flows

- F1. **Trigger:** User submits the dialog with a new, unique source/reference.
  - **Steps:** Save via the existing job-save flow (creates the job offer and its draft application) → navigate to the application editor for the new job offer.
  - **Outcome:** The editor finds no cover letter yet and generates one automatically; the card is already visible back on the Applications list.
  - **Covers:** R1, R2, R4, R5, R7, R8.
- F2. **Trigger:** User submits the dialog with a source/reference that matches an already-saved job offer.
  - **Steps:** The save request returns a conflict.
  - **Outcome:** The dialog shows the conflict and offers to open the already-existing application instead of creating a duplicate.
  - **Covers:** R6.

### Acceptance Examples

- AE1. **Covers R5, R7.** Given a directly-found job offer with a unique reference, when the user submits the dialog, then a job offer and draft application are created and the user lands in the application editor with the cover letter auto-generating.
- AE2. **Covers R6.** Given a reference that matches an already-saved job offer, when the user submits the dialog, then it shows the conflict and offers a way to open the existing application instead of creating a duplicate.
- AE3. **Covers R2.** Given only the required fields (title, company, source/reference) are filled in and description/application email are left blank, when the user submits, then the save succeeds — no additional fields are enforced.

### Scope Boundaries

- Location on manually-added offers — omitted from the dialog even though scraped offers show it on the card (see the Key Decision governing R3).
- A dedicated backend endpoint or schema for manual entries — not built; the existing job-offer create schema and save endpoint are reused as-is (see the Key Decision governing R5, R8).

### Sources / Research

- `backend/app/api/jobs.py` — `POST /jobs/save` already creates a `JobOffer` plus an empty draft `Application` in one step, and already returns a `409` with the existing `job_offer_id` on a duplicate `source_url`.
- `backend/app/models/job_offer.py` / `backend/app/schemas/job_offer.py` — `source_url` is the only unique, required identity field; `source_platform` is a free-form string with no backend-enforced enum, so a new value needs no migration.
- `frontend/src/app/pages/application-editor/application-editor.component.ts` (`loadOrGenerateApplication`) — the editor already auto-triggers generation on load whenever `cover_letter_text` is empty, which is exactly the state a freshly-saved manual entry is in.
- `frontend/src/app/pages/job-search/job-search.component.ts` — existing pattern for handling the `409`/`JobSaveConflictDetail` response, reused for R6.
- `frontend/src/app/core/utils/source-label.util.ts` — existing platform-label map that a new `manual` entry extends.
- `CONCEPTS.md` ("Applied") — confirms saved and "on the Applications page" already describe the same set today, so R8 needs no new logic.

---

**Product Contract preservation:** restructured, no scope change — the Key Decisions bullets dropped their non-conforming `KTD<N>.` prefixes (brainstorm Product Contract decisions carry no numeric ID; `KTD` is reserved for the Planning Contract below). Wording, rationale, `Governs` links, and `session-settled` annotations are unchanged.

## Planning Contract

Backend needs no changes: `POST /jobs/save` (`backend/app/api/jobs.py`) already accepts every field this feature needs (`JobOfferCreate`: `title`, `company`, `location`, `source_url`, `description_text`, `source_platform`, `application_email`, `application_email_source_url`), already creates the draft `Application` in the same request, and already returns `409` with the conflicting `job_offer_id`. This plan is frontend-only.

### Key Technical Decisions

- KTD1. Extract `JobSearchComponent`'s existing private 409-conflict parser into one shared, exported helper instead of writing a third copy of the same logic for the new applications-page flow. Governs implementation of R6.
- KTD2. `ApplicationsComponent` calls `JobService.saveJob()` directly and runs the save-then-navigate-or-redirect-on-conflict sequence itself, mirroring `JobSearchComponent.onGenerateApplication`'s existing pattern (`frontend/src/app/pages/job-search/job-search.component.ts:298-333`), rather than adding a new service method. (session-settled: user-approved — inherits the Product Contract decision to reuse the existing job-save endpoint; this is the how-level choice that instantiates it) Governs R5, R6, R7, R8.
- KTD3. The new `AddJobOfferDialogComponent` only collects and validates form data and makes no HTTP calls itself; `ApplicationsComponent` performs the save after the dialog closes, mirroring `SendApplicationDialogComponent`'s existing collect-then-parent-executes pattern (`frontend/src/app/pages/application-editor/send-application-dialog/send-application-dialog.component.ts`). Governs R1, R2.
- KTD4. Manually-entered offers use `source_platform: 'manual'`, added to `SOURCE_LABELS` in `source-label.util.ts` as `"Direct"`. Governs R4.
- KTD5. On a non-409 save failure, the user re-enters the form from scratch rather than the dialog reopening pre-filled with their prior input. Reopening-with-prefill would require the dialog's form state to outlive the dialog's own destruction, adding real complexity for a transient-failure edge case. Governs U4.

---

## Implementation Units

### U1. Shared job-save-conflict helper

- **Goal:** Stop the 409-conflict-parsing logic from being duplicated a third time.
- **Requirements:** R6. KTD1.
- **Dependencies:** None.
- **Files:**
  - `frontend/src/app/core/services/job.service.ts`
  - `frontend/src/app/pages/job-search/job-search.component.ts`
  - `frontend/src/app/core/services/job.service.spec.ts`
- **Approach:**
  1. Add an exported function in `job.service.ts`, e.g. `jobSaveConflictId(error: HttpErrorResponse): number | null`, with the same body as `JobSearchComponent.conflictJobOfferId` (`frontend/src/app/pages/job-search/job-search.component.ts:342-348`).
  2. Update `JobSearchComponent.onSaveJob` and `onGenerateApplication` to call the shared helper.
  3. Delete `JobSearchComponent`'s now-redundant private `conflictJobOfferId` method.
- **Patterns to follow:** `frontend/src/app/core/models/job-offer.model.ts`'s `toApplicationEmailLookupRequest` — an existing exported pure function living next to the model/service it serves.
- **Test scenarios:**
  - Given an `HttpErrorResponse` with status 409 and a numeric `job_offer_id` in `error.error.detail`, the helper returns that id.
  - Given a 409 response with a missing or non-numeric `job_offer_id`, the helper returns `null`.
  - Given a non-409 status, the helper returns `null` regardless of body.
- **Verification:** New `job.service.spec.ts` cases pass; `job-search.component.spec.ts`'s existing conflict-handling tests still pass unchanged.

### U2. `manual` source label

- **Goal:** Give manually-added job offers their own display label.
- **Requirements:** R4. KTD4.
- **Dependencies:** None.
- **Files:** `frontend/src/app/core/utils/source-label.util.ts`
- **Approach:** Add `manual: 'Direct'` to `SOURCE_LABELS`.
- **Test expectation:** none -- a one-entry addition to an existing data table; `sourceLabel()`'s fallback-to-raw-key behavior for unmapped values is already covered by existing tests, and this doesn't add branching logic.
- **Verification:** `sourceLabel('manual')` returns `'Direct'` (asserted inline within U4's applications-component tests, where a saved manual offer's card renders the label).

### U3. Add-job-offer dialog component

- **Goal:** Build the dialog that collects a directly-found job offer's details.
- **Requirements:** R1, R2, R3. KTD3.
- **Dependencies:** None.
- **Files:**
  - `frontend/src/app/pages/applications/add-job-offer-dialog/add-job-offer-dialog.component.ts`
  - `frontend/src/app/pages/applications/add-job-offer-dialog/add-job-offer-dialog.component.html`
  - `frontend/src/app/pages/applications/add-job-offer-dialog/add-job-offer-dialog.component.scss`
  - `frontend/src/app/pages/applications/add-job-offer-dialog/add-job-offer-dialog.component.spec.ts`
- **Approach:**
  1. Mirror `SendApplicationDialogComponent`'s `MAT_DIALOG_DATA`/`MatDialogRef`/reactive-form shell (no input data needed here — the dialog starts blank).
  2. Form fields, each labeled per this row: `title` (label "Job title", `Validators.required`); `company` (label "Company", `Validators.required`); `source_url` (label "Source / reference", placeholder/helper text "Paste the job posting link, or describe where you found it", `Validators.required`); `description_text` (label "Job description", optional, textarea, helper copy noting it improves the generated cover letter); `application_email` (label "Application email", optional, `Validators.email` only, no `required`).
  3. `onConfirm()` validates (`form.invalid` guard, `markAllAsTouched()` on failure, same as `SendApplicationDialogComponent.onConfirm`) and closes with a typed `AddJobOfferDialogResult` (the five field values). `onCancel()` closes with no result. Backdrop-click and Escape use `MatDialog`'s default dismiss-with-no-result behavior, same as `SendApplicationDialogComponent` today — no unsaved-input guard.
- **Patterns to follow:** `frontend/src/app/pages/application-editor/send-application-dialog/send-application-dialog.component.ts` for the dialog shell and validation-guard shape.
- **Test scenarios:**
  - Given all fields are filled in, when the user confirms, then the dialog closes with the expected result shape (Covers AE1).
  - Given `title` or `company` is empty, when the user tries to confirm, then the dialog does not close and marks the invalid fields touched.
  - Given `source_url` is empty, when the user tries to confirm, then the dialog blocks submission (Covers R2).
  - Given `description_text` and `application_email` are left blank, when the user confirms, then the dialog still closes successfully (Covers AE3).
  - Given `application_email` has an invalid format, when the user tries to confirm, then the dialog blocks submission.
  - Given the user clicks cancel, when the dialog closes, then it emits no result.
- **Verification:** New `add-job-offer-dialog.component.spec.ts` passes, covering the scenarios above.

### U4. Wire the dialog into the Applications page

- **Goal:** Add the entry point and the save/navigate/conflict flow.
- **Requirements:** R1, R4, R5, R6, R7, R8. KTD2, KTD5.
- **Dependencies:** U1, U2, U3.
- **Files:**
  - `frontend/src/app/pages/applications/applications.component.ts`
  - `frontend/src/app/pages/applications/applications.component.html`
  - `frontend/src/app/pages/applications/applications.component.spec.ts`
- **Approach:**
  1. Add an "Add job offer" button near the page header, opening `AddJobOfferDialogComponent` via `MatDialog.open(...)`.
  2. On `afterClosed()` with a result, build a `JobOffer` payload: form fields plus `location: null`, `source_platform: 'manual'`, `application_email_source_url: null`.
  3. Call `JobService.saveJob(payload)`. On success, navigate to `/editor/:id` (mirrors `JobSearchComponent.onGenerateApplication`'s happy path).
  4. On error, call U1's `jobSaveConflictId` helper; if it returns an id, navigate to `/editor/:existing-id` and show a snackbar noting it was already saved (Covers R6); otherwise show a generic save-failed snackbar.
  5. Add a `savingNewJobOffer` signal (same convention as `deletingId`/`updatingStatusId` in this component) to disable the trigger button and show a spinner while the request is in flight.
- **Patterns to follow:** `frontend/src/app/pages/job-search/job-search.component.ts`'s `onGenerateApplication` (`:298-333`) for the save-then-navigate-or-conflict sequence, now via U1's shared helper instead of a duplicated one.
- **Test scenarios:**
  - Given the dialog returns a valid result, when saved successfully, then `JobService.saveJob` is called with `source_platform: 'manual'` and `location: null`, and the router navigates to `/editor/:new-id` (Covers AE1, R5, R7).
  - Given the save request returns a 409 with an existing `job_offer_id`, when handled, then the router navigates to `/editor/:existing-id` instead of showing a dead end (Covers AE2, R6).
  - Given the save request fails with a non-409 error, when handled, then a generic error snackbar is shown and no navigation occurs.
  - Given the dialog is cancelled (no result), when closed, then no save request is made.
  - Given only the required fields were filled in (Covers AE3), when saved, then the request succeeds with `description_text`/`application_email` omitted or `null`.
  - Given a manually-saved job offer appears in the list, then its card renders the `"Direct"` source label (Covers R4, U2).
  - Given the save request fails with a non-409 error, when the user reopens the dialog, then it starts blank rather than pre-filled (Covers KTD5).
- **Verification:** `applications.component.spec.ts` covers the above via `HttpTestingController` and a router test double, consistent with the spec's existing HTTP-mocking style.

---

## Verification Contract

| Command | Applicability |
|---|---|
| `cd frontend && npm test` | All units (U1-U4) — Angular unit tests via `ng test`. |
| `cd backend && pytest` | Regression check only — no backend files change in this plan; existing `test_jobs.py`/`test_applications.py` must stay green. |

Manual smoke (not required for DoD, useful before shipping): from the Applications page, add a job offer with only the required fields, confirm it lands in the editor and the cover letter starts generating; repeat with a source/reference that was already saved and confirm it opens the existing application instead of erroring.

---

## Definition of Done

- All four units implemented; `cd frontend && npm test` passes.
- `cd backend && pytest` still passes (no backend behavior changed).
- `JobSearchComponent`'s duplicate 409-parsing method is removed, not left alongside the new shared helper (U1 cleanup).
- A manually-added offer's card renders the `"Direct"` source label (U2).
- No dead-end on a duplicate reference: the user reaches the existing application instead of an error page (R6, AE2).
