---
title: Applications Search & Sent Mail Outcome - Plan
type: feat
date: 2026-09-22
topic: applications-search-sent-mail-outcome
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Applications Search & Sent Mail Outcome - Plan

## Goal Capsule

- **Objective:** add a company/title search to the Applications list, and an Outcome (Offer / Rejection / Pending) field plus filter to the Sent Mails log — two independent, small filter additions to the existing personal job-application tracker.
- **Product authority:** the `ce-brainstorm` dialogue (2026-09-22) for product scope; this Planning Contract for implementation decisions. No `STRATEGY.md` exists in this repo.
- **Execution profile:** standard code implementation. No goal-mode or dynamic-workflow special casing needed.
- **Stop conditions:** surface a blocker rather than guessing if implementation finds the outer-join filter shape (KTD3), the export filter-parity call (KTD2), or the `outcome` naming choice (KTD1) does not hold as researched.
- **Open blockers:** none — implementation-ready.

## Product Contract

**Preservation:** unchanged from the requirements-only version of this file — no Requirements, Key Decisions, or Scope Boundaries were altered during planning.

### Summary

Add a free-text search to the Applications page that matches company or job title, layered on top of the existing status filter. Add an Outcome column and filter to the Sent Mails log, showing Offer / Rejection / Pending per logged send based on the linked application's current status.

### Requirements

**Applications search**
- R1. The Applications page has a free-text search input that matches a case-insensitive substring against either the job title or the company name.
- R2. The search combines with the existing status filter (AND) rather than replacing it — e.g. searching "Acme" while the Rejected tab is active narrows within rejected applications only.

**Sent Mails outcome**
- R3. Each Sent Mails log entry displays an Outcome of Offer, Rejection, or Pending, derived from the current status of its linked application — not a snapshot of the status at send time.
- R4. An entry shows Outcome "Pending" when its linked application has no decision yet (draft, sent, or interview status) or when the application has since been deleted.
- R5. The Sent Mails page has an Outcome filter offering All, Offer, Rejection, and Pending.
- R6. Outcome is not added to the PDF export (filtered or full-log) — both exports keep their current columns.

### Key Decisions

- **Grouping of rejected applications dropped.** The existing status filter already isolates rejected applications; a separate grouped/sectioned layout wasn't worth the added complexity. *(session-settled: user-directed — chosen over sketching a grouped layout: the existing filter already covers the need)*
- **Outcome reflects live application status, not a send-time snapshot.** Consistent with how the log already links live to its application elsewhere (e.g. its edit-page link): a resent application shows its current outcome on every one of its log rows, and an outcome can change after the email was sent. Governs R3.
- **No-outcome entries show as "Pending" and are filterable**, rather than a blank cell with no matching filter option. Governs R4, R5. *(session-settled: user-directed — chosen over a blank cell with no Pending filter option: lets you isolate entries still awaiting a decision)*
- **Outcome stays on-screen only, not in the PDF export.** Both exports keep their current columns unchanged. Governs R6. *(session-settled: user-directed — chosen over adding Outcome to both exports: PDF export wasn't part of the need)*
- **Applications search combines with the existing status filter.** Search narrows within whichever status tab is active rather than resetting it. Governs R1, R2.

### Acceptance Examples

- AE1. **Covers R3, R4.** Given a sent email whose linked application has status `rejected`, when viewing the Sent Mails log, then Outcome shows "Rejection".
- AE2. **Covers R3, R4.** Given a sent email whose linked application has status `accepted`, then Outcome shows "Offer".
- AE3. **Covers R3, R4.** Given a sent email whose linked application is still `draft`, `sent`, or `interview`, then Outcome shows "Pending".
- AE4. **Covers R3, R4.** Given a sent email whose linked application has since been deleted, then Outcome shows "Pending".
- AE5. **Covers R5.** Given the Outcome filter is set to "Rejection", then only entries whose linked application is `rejected` appear.
- AE6. **Covers R1, R2.** Given the Applications status filter is set to "Rejected" and the search text is "Acme", then only rejected applications whose title or company contains "Acme" (case-insensitive) appear.

### Scope Boundaries

- Visual grouping or sectioning of rejected applications in the Applications list — dropped (see Key Decisions).
- Outcome column in the Sent Mails PDF export (the row-filtering behavior of the `outcome` query parameter still applies to the export endpoint per KTD2 — only the rendered column is excluded).
- Setting or changing an application's Offer/Rejection status from the Sent Mails page — Outcome there is read-only; the status toggle stays on the Applications page as today.

### Sources / Research

- `frontend/src/app/pages/applications/applications.component.ts` — existing client-side status filter (`ApplicationFilter`, `filteredApplications` computed signal) the search input extends.
- `backend/app/api/sent_emails.py` and `backend/app/schemas/sent_email.py` — existing server-side filter contract (`SentEmailFilter`, `_apply_filters`) shared by the list and export endpoints; the Outcome filter extends this contract for the list endpoint only (per R6).
- `backend/app/models/sent_email.py` — documents the existing live-vs-snapshot split (`company`/`job_title` snapshotted, `job_offer_id`/`ad_url` live via the `application` relationship) that the Outcome decision follows.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **The new outcome value is a plain string (`"offer"` / `"rejection"` / `"pending"`), kept separate from the unrelated "Run outcome" portal-auto-fill concept already in `CONCEPTS.md`.** The Sent Mails page's "Outcome" label matches the word the Applications page already uses for this same accept/reject decision (`frontend/src/app/pages/applications/applications.component.html:48`), so the UI term stays consistent; the code-level type is a bare string rather than a shared enum, so it never couples to portal-fill's run-outcome type. Governs R3, R4, R5.
- KTD2. **The `outcome` query filter applies to `GET /sent-emails/export` as well as `GET /sent-emails`, following the filter-parity contract already documented on `_apply_filters`/`_base_query` (`backend/app/api/sent_emails.py:22-42`)**, so "export the current view" keeps returning the same rows the list shows. R6 scopes only the rendered PDF column, not the row-filtering behavior, so this is not a change to R6 — only the Outcome column stays out of the PDF. `GET /sent-emails/export/all` stays filterless, as today. Governs R5, R6.
- KTD3. **Outcome filtering joins `Application` with an `outerjoin`, not an inner join.** An inner join would silently drop "pending because the application was deleted" rows (`application_id IS NULL`) from the Pending filter option. Governs R4, R5.
- KTD4. **The Applications search extends the existing `filteredApplications` `computed()` signal in place** (`frontend/src/app/pages/applications/applications.component.ts:160-166`), adding a second chained predicate, rather than a new filter service or pipe. Matches the codebase's one existing precedent for signal-based list filtering (`job-search.component.ts`'s `selectedSources`/`filteredResults`), scaled from one predicate to two. Governs R1, R2.

### Assumptions

- The Sent Mails Outcome filter renders as a `mat-select` with four options (All, Offer, Rejection, Pending), mirroring the existing sender-email `mat-select`.
- No database migration is needed — `outcome` is a computed `@property`, never a stored column, per KTD1 and the `job_offer_id`/`ad_url` precedent it follows.

### Sources / Research

- `frontend/src/app/pages/applications/applications.component.ts:141,160-166` — `filter` signal + `filteredApplications` `computed()`, the pattern U1 extends.
- `frontend/src/app/pages/job-search/job-search.component.ts` (`selectedSources`/`filteredResults`) — the codebase's only other computed-signal filter; no existing page combines two predicates, so U1's AND-combination is new, not a copy.
- `frontend/src/app/pages/applications/applications.component.spec.ts:210-224` — existing filter test to mirror for U1.
- `backend/app/api/sent_emails.py:14,22-42,52-60` — `_apply_filters`/`_base_query`, the shared filter chain U3 extends; the filter-parity contract behind KTD2 is documented in this file's own comments.
- `backend/app/models/sent_email.py:73-86` — `job_offer_id`/`ad_url` `@property` pattern, the template for U2's `outcome` property.
- `backend/app/models/application.py:15-22,38-43` — `ApplicationStatus` enum and the indexed `status` column `outcome` reads.
- `backend/tests/api/test_sent_emails.py:53-66,249-277` — existing `_insert_sent_email` helper and the JobOffer+Application-row test setup U2/U3's tests must follow (a bare `application_id=1` with no real `Application` row will not exercise the join).
- `docs/solutions/test-failures/fastapi-testclient-sqlite-memory-pool-and-lifespan-isolation.md` — `StaticPool` + non-`with` `TestClient` fixture pitfalls to avoid in any new or extended backend test file.
- Test commands: frontend `cd frontend && npm run test:vitest` (specs use Vitest APIs directly; `npm test`/`ng test` still wire up the legacy Karma builder but do not reflect what actually runs the specs); backend `cd backend && pytest`.

---

## Implementation Units

### U1. Applications company/title search

- **Goal:** add a free-text search input to the Applications page that narrows the list by company or job title, combined with the existing status filter.
- **Requirements:** R1, R2
- **Dependencies:** none
- **Files:**
  - `frontend/src/app/pages/applications/applications.component.ts`
  - `frontend/src/app/pages/applications/applications.component.html`
  - `frontend/src/app/pages/applications/applications.component.spec.ts`
- **Approach:**
  - Add `protected readonly searchTerm = signal('');`.
  - Add a private `matchesSearch(application: Application, term: string): boolean` checking `application.job_offer.title` and `application.job_offer.company` (case-insensitive substring); an empty term always matches.
  - Extend the existing `filteredApplications` `computed()` (KTD4) to chain the status predicate with `matchesSearch`, so both apply (AND).
  - Add a `mat-form-field` text input above or beside the existing status button-toggle group, bound with `(input)="searchTerm.set($any($event.target).value)"` — live client-side update, no submit button, no `onFilterChange()`-style HTTP round trip (this filter never leaves the browser).
  - Update the empty-state copy at `applications.component.html:62` ("No applications with this status.") so it is no longer status-only wording once search can also be the reason the list is empty — branch on whether `searchTerm()` is non-empty, mirroring how `sent-emails.component.html` already branches its empty message on `hasActiveFilter()`.
- **Patterns to follow:** `filter`/`filteredApplications` signal-and-computed pair (`applications.component.ts:141,160-166`); Material text-input markup from `frontend/src/app/pages/sent-emails/sent-emails.component.html:9-16` (syntax only — bind directly here, not through `onFilterChange()`).
- **Test scenarios:**
  - Search text matching company (case-insensitive) narrows the list to only matches.
  - Search text matching title (case-insensitive) narrows the list to only matches. Covers AE6.
  - Search combined with an active status filter narrows within that status only. Covers AE6.
  - Empty search shows every application within the active status filter (no behavior change from today).
  - Search text matching neither field returns an empty list, with empty-state copy that reflects the active search (not just the status filter).
- **Verification:** `cd frontend && npm run test:vitest`; extend the existing filter test in `applications.component.spec.ts:210-224`.

### U2. Sent Mail outcome derived field

- **Goal:** expose an Offer/Rejection/Pending outcome per Sent Mails log entry, derived live from the linked application's status.
- **Requirements:** R3, R4
- **Dependencies:** none
- **Files:**
  - `backend/app/models/sent_email.py`
  - `backend/app/schemas/sent_email.py`
- **Approach:**
  - Add an `outcome` `@property` on `SentEmail`, mirroring the `job_offer_id`/`ad_url` shape (`sent_email.py:73-86`): return `"pending"` when `self.application is None`; `"offer"` when `self.application.status == ApplicationStatus.ACCEPTED`; `"rejection"` when `== ApplicationStatus.REJECTED`; `"pending"` otherwise (draft, sent, interview). Per KTD1, the return type is `str`, not a shared enum.
  - Add `outcome: str` to `SentEmailRead` (`schemas/sent_email.py`) alongside `job_offer_id`/`ad_url` — `from_attributes=True` is already set, so the property is picked up with no extra wiring.
- **Patterns to follow:** `job_offer_id`/`ad_url` `@property` pattern, `backend/app/models/sent_email.py:73-86`.
- **Test scenarios:**
  - Entry whose linked application has status `rejected` → `outcome == "rejection"`. Covers AE1.
  - Entry whose linked application has status `accepted` → `outcome == "offer"`. Covers AE2.
  - Entry whose linked application has status `draft`, `sent`, or `interview` → `outcome == "pending"`. Covers AE3.
  - Entry whose `application_id` is null (application deleted) → `outcome == "pending"`. Covers AE4.
  - Build these tests on a real `JobOffer` + `Application` row (`test_sent_emails.py:249-277` pattern), not the bare `application_id=1` shortcut — the property needs the live relationship.
- **Verification:** `cd backend && pytest tests/api/test_sent_emails.py`.

### U3. Outcome filter on the Sent Mails query contract

- **Goal:** let `GET /sent-emails` and `GET /sent-emails/export` narrow results by Outcome.
- **Requirements:** R5
- **Dependencies:** U2
- **Files:**
  - `backend/app/schemas/sent_email.py`
  - `backend/app/api/sent_emails.py`
- **Approach:**
  1. Add `outcome: str | None = None` to `SentEmailFilter`, same flat-optional-field style as `company`/`sender_email`.
  2. In `_apply_filters`, when `filters.outcome` is set: outer-join `Application` (KTD3), then filter by status per the value (`offer` → `ACCEPTED`; `rejection` → `REJECTED`; `pending` → status is null or not in `{ACCEPTED, REJECTED}`).
  3. This lives in the shared `_apply_filters`/`_base_query`, so it applies to both list and export queries per KTD2. `/sent-emails/export/all` is untouched (always uses an empty `SentEmailFilter()`).
- **Technical design (directional):**
  ```python
  if filters.outcome:
      query = query.outerjoin(Application, SentEmail.application_id == Application.id)
      if filters.outcome == "offer":
          query = query.filter(Application.status == ApplicationStatus.ACCEPTED)
      elif filters.outcome == "rejection":
          query = query.filter(Application.status == ApplicationStatus.REJECTED)
      else:
          query = query.filter(
              or_(
                  Application.status.is_(None),
                  Application.status.notin_([ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED]),
              )
          )
  ```
- **Patterns to follow:** existing `_apply_filters` chain (`backend/app/api/sent_emails.py:22-37`) — this is the repo's first related-table join filter, so this unit's Approach is the concrete shape to implement, not a pointer to a precedent.
- **Test scenarios:**
  - `?outcome=rejection` returns only entries linked to a rejected application. Covers AE5.
  - `?outcome=offer` returns only entries linked to an accepted application.
  - `?outcome=pending` returns entries linked to a draft/sent/interview application, and entries with no linked application (deleted).
  - `outcome` combines with `company`/`date_from`/`date_to` (AND), same as existing filters.
  - `GET /sent-emails/export?outcome=rejection` returns the same filtered row set as the list endpoint (filter parity per KTD2), even though the PDF renders no Outcome column (R6).
  - No `outcome` param → unchanged existing behavior (regression check).
- **Verification:** `cd backend && pytest tests/api/test_sent_emails.py`.

### U4. Sent Mails page: Outcome column and filter

- **Goal:** show Offer/Rejection/Pending per row on the Sent Mails page and let the user filter by it.
- **Requirements:** R3, R4, R5
- **Dependencies:** U2, U3
- **Files:**
  - `frontend/src/app/core/models/sent-email.model.ts`
  - `frontend/src/app/pages/sent-emails/sent-emails.component.ts`
  - `frontend/src/app/pages/sent-emails/sent-emails.component.html`
  - `frontend/src/app/pages/sent-emails/sent-emails.component.spec.ts`
- **Approach:**
  - Add `outcome: 'offer' | 'rejection' | 'pending'` to the `SentEmail` interface, and `outcome?: string | null` to `SentEmailFilterParams`.
  - Add `protected readonly outcomeFilter = signal<string | null>(null);`, include it in `currentFilter()`, and add `'outcome'` to `displayedColumns`, rendered via a small label map (Offer/Rejection/Pending) mirroring `statusLabel`'s shape in `applications.component.ts:168-174`.
  - Add a `mat-select` Outcome filter (All/Offer/Rejection/Pending) next to the existing sender-email `mat-select`, wired to `onFilterChange()` like the other server-side filters.
  - Extend `hasActiveFilter()` to treat a non-null `outcomeFilter()` as an active filter.
- **Patterns to follow:** filter-signal-into-`currentFilter()` pattern (`sent-emails.component.ts:80-99,173-180`); existing sender-email `mat-select` markup.
- **Test scenarios:**
  - Selecting "Rejection" triggers a reload with `outcome: 'rejection'` in the request. Covers AE5.
  - Table renders "Offer"/"Rejection"/"Pending" labels per row from `entry.outcome`.
  - `hasActiveFilter()` returns true when only the Outcome filter is set.
- **Verification:** `cd frontend && npm run test:vitest`.

---

## Verification Contract

| Scope | Command | Applies to |
|---|---|---|
| Frontend unit tests | `cd frontend && npm run test:vitest` | U1, U4 |
| Backend Sent Mails tests | `cd backend && pytest tests/api/test_sent_emails.py` | U2, U3 |
| Backend full suite (regression) | `cd backend && pytest` | U2, U3 |

## Definition of Done

- U1-U4 implemented; every test scenario listed above passes.
- `cd frontend && npm run test:vitest` and `cd backend && pytest` both pass with no regressions.
- Neither `/sent-emails/export` nor `/sent-emails/export/all` renders an Outcome column (R6) — verify against `backend/app/services/pdf_service.py`'s `_sent_email_row`/template.
- No dead-end or experimental code left from approaches explored during implementation.
