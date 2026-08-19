---
title: CV-Only Email Attachment - Plan
type: feat
date: 2026-08-19
topic: cv-only-email-attachment
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# CV-Only Email Attachment - Plan

## Goal Capsule

- **Objective:** Replace the combined Anschreiben+CV PDF with a CV-only PDF, used consistently for the application editor's live preview, the manual PDF download, and the email attachment. Pre-fill the email's Subject and Message from the Anschreiben text instead of sending a second attachment or generic boilerplate.
- **Product authority:** The Product Contract below is authoritative for behavior. **Product Contract preservation: unchanged** — planning added no scope change; all R-IDs, Key Decisions, and Acceptance Examples from the brainstorm carry forward as written.
- **Stop conditions:** Stop and ask before overriding a labeled Key Decision or KTD below if implementation shows it is technically infeasible. Stop if a unit's scope would need to grow into product-behavior territory not covered by a Requirement.
- **Execution profile:** `execution: code`. Backend: FastAPI/SQLAlchemy, Python, pytest. Frontend: Angular, Karma/Jasmine. No CI, deployment, or infrastructure changes.
- **Tail ownership:** Implementer runs `pytest` (backend) and `ng test` (frontend). This plan prescribes no PR/branch/deploy sequencing.
- **Open blockers:** None.

## Product Contract

### Summary

The email-send flow currently attaches one combined Anschreiben+CV PDF and sends it with a generic boilerplate body. This proposes splitting the two: the email attaches only a CV-only PDF, and the Anschreiben text becomes the email's Subject (its "Betreff: ..." line) and Message (the rest of the letter), pre-filled and editable before sending. The same CV-only PDF also replaces the combined document in the editor's live preview and manual download.

### Problem Frame

German job-application emails conventionally carry the cover letter as the email's own text, with only the CV as a PDF attachment — not a cover letter buried inside a PDF plus a generic "please find attached" body. The current flow (`backend/app/services/pdf_service.py`, `backend/app/api/applications.py`) renders Anschreiben and CV into one PDF and sends a boilerplate body regardless of what the user wrote as their Anschreiben, so the actual cover-letter text the user (and the AI) crafted never reaches the recipient as readable email text.

### Requirements

**PDF rendering**

- R1. The application's PDF renderer produces a CV-only PDF (no Anschreiben content) from the tailored CV data.
- R2. The CV-only PDF is the single artifact used for the editor's live preview, the manual "Download PDF" action, and the email attachment — the combined Anschreiben+CV renderer is retired, not kept as a second output alongside the new one.
- R3. The CV-only PDF's filename is `lebenslauf_{application_id}.pdf` for the download action, the inline preview, and the email attachment, replacing the current `bewerbung_{application_id}.pdf`.

**Email composition**

- R4. The email's Subject field is pre-filled from the Anschreiben text's leading "Betreff: ..." line, with the "Betreff:" label removed, shown to the user in the send dialog before sending and editable there.
- R5. The email's Message field is pre-filled with the Anschreiben text minus its leading "Betreff: ..." line, shown to the user in the send dialog before sending and editable there.
- R6. When the Anschreiben text has no parseable "Betreff: ..." line, the Subject field falls back to today's default (job-title-based when a job offer is linked, otherwise the existing generic default).
- R7. The stored Anschreiben text — in the database and the editor's cover-letter field — is not modified by this feature. The Betreff line stays part of the saved text; only the values derived for the Subject/Message fields strip and extract it.

### Key Decisions

- **CV-only PDF replaces the combined document everywhere, not only for email** (session-settled: user-directed — chosen over keeping the combined PDF for preview/download and changing only the email attachment). Governs R2.
- **Subject/Message are visibly pre-filled and editable in the send dialog, not a silent send-time default** (session-settled: user-directed — the user asked for the Betreff text to be added to the Subject input field itself). Governs R4, R5.
- **CV filename renamed to `lebenslauf_{application_id}.pdf`** (session-settled: user-directed — chosen over keeping `bewerbung_{application_id}.pdf`, for naming accuracy now that the file is CV-only). Governs R3.
- **Stored Anschreiben text is left untouched; stripping/extraction applies only to the derived Subject/Message values** (session-settled: user-approved — surfaced as a call-out during synthesis, confirmed). Governs R7.

### Acceptance Examples

- AE1. **Covers R4, R5.** Given a saved application whose Anschreiben text is `"Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,\n\n...\n\nMit freundlichen Grüßen\nMax Mustermann"`, when the user opens the send-email dialog, then the Subject field shows `"Bewerbung als Softwareentwickler"` and the Message field shows the text starting at `"Sehr geehrte Damen und Herren,"` through the closing signature — both editable before sending.
- AE2. **Covers R6.** Given an Anschreiben text with no `"Betreff: ..."` line, when the send-email dialog opens, then the Subject field falls back to today's default subject.
- AE3. **Covers R2, R3.** Given an application, when the user downloads its PDF, previews it in the editor, or sends its email, then all three actions deliver/show the same CV-only PDF named `lebenslauf_{application_id}.pdf`.

### Scope Boundaries

- No multi-attachment support — the email still carries exactly one PDF attachment (the CV).
- No change to how the AI generates the Anschreiben text — it still produces a single string with a Betreff line, salutation, body, and closing.
- No change to the existing "E-Mail-Text" tab's `to_email` field, or to send-failure/retry handling — both stay as they are today (see KTD3, and the retry note under Planning Contract Assumptions).

### Dependencies / Assumptions

- Existing applications' previously-generated combined PDF stays on disk unchanged until the application is next edited and saved, which regenerates the PDF via the CV-only renderer. No explicit migration or backfill step is in scope. This means the rename (R3) is filename-only for such applications until their next save: the served/attached file is already named `lebenslauf_{id}.pdf`, but its content is still the old combined document until the application is next edited and saved — an accepted transitional state, confirmed during planning.
- The Anschreiben text's "Betreff: ..." line is assumed to be the first non-empty line of the text when present (per current AI-generation format in `backend/app/services/ai_generator.py`); manually-edited text without a Betreff line falls back per R6.

### Sources / Research

- `backend/app/services/pdf_service.py:1-9,48-83` — current combined-PDF renderer (`render_application_pdf`) and its documented rationale (one PDF for consistent pagination), to be retired in favor of a narrower `render_cv_pdf`.
- `backend/app/templates/application.html:28-199` — `.cover-letter` and `.cv` sections/CSS of the current combined template; `.cv { page-break-before: always }` at line 66 is the rule that forces the CV onto page 2 and must be dropped for a CV-only template.
- `backend/app/services/mail_service.py:19-45` — single-attachment email sending (`MIMEApplication` built once); confirmed no multi-attachment support exists anywhere in this file or its callers.
- `backend/app/api/applications.py` — `_pdf_path_for` (on-disk path, unaffected by the rename), `GET /{id}/pdf` (line 231, inline `Content-Disposition` filename), `POST /{id}/send` (line 252 default subject, lines 254-259 default body text, line 268 attachment filename), `POST /generate` (line 76) and `PUT /{id}` (line 169) render call sites.
- `backend/app/services/ai_generator.py:46` — Anschreiben generation format, confirming the `"Betreff: ..."` leading-line convention the parser targets.
- `frontend/src/app/pages/application-editor/application-editor.component.ts` — `emailForm` (lines 106-110, the existing "E-Mail-Text" tab), `coverLetterForm` (lines 96-98, must stay untouched per R7), `onOpenSendDialog` (lines 367-394), `onDownloadPdf` (lines 343-365, filename literal at line 356), `loadPdfPreview` (lines 204-219, shares the `GET /{id}/pdf` endpoint with download so it inherits CV-only content automatically).
- `frontend/src/app/pages/application-editor/send-application-dialog/` — `SendApplicationDialogData`/`Result` contracts (unchanged shape; only the parent's initial values change) and the existing "Wird sonst automatisch gesetzt" placeholder hint.
- Backend tests: pytest via `backend/pytest.ini`, pattern in `backend/tests/api/test_applications.py` (FastAPI `TestClient` + in-memory SQLite). No existing tests for `pdf_service.py` or `mail_service.py`.
- Frontend tests: Karma/Jasmine via `ng test` (`frontend/angular.json`), pattern in `application-editor.component.spec.ts` (`TestBed` + `HttpTestingController`). No existing `.spec.ts` for `send-application-dialog.component.ts`.
- No relevant prior learnings found in `docs/solutions/` (`integration-issues/`, `test-failures/`) — this is new territory for PDF rendering and email-sending in this repo's knowledge base.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Betreff-parsing is a frontend-only TypeScript utility, matching the first non-empty line of the text, case-insensitively.** No shared backend regex-utility convention exists (`job_sources/xing.py`, `job_search_service.py` each define their own compiled patterns), and parsing here only feeds a UI pre-fill, not backend email logic. Governs R4, R5, R6.
- KTD2. **Subject/Message derive from the saved `cover_letter_text`, never the live unsaved editor value** (session-settled: user-directed — chosen over deriving from unsaved text: keeps the email text consistent with the CV/application state that's actually attached). Governs R4, R5.
- KTD3. **The existing "E-Mail-Text" tab's Subject/Message fields remain an explicit override; Betreff-derivation is the default only when those fields are empty** (session-settled: user-directed — chosen over retiring the tab or making it the sole source of truth). Governs R4, R5.
- KTD4. `render_application_pdf` is replaced in place by a narrower `render_cv_pdf(cv: TailoredCv) -> bytes`, dropping the now-unused `cover_letter_text`/`job_offer` parameters, rather than kept alongside a second function. Governs R1, R2.
- KTD5. Filename rename covers all three user-facing occurrences of `bewerbung_{id}.pdf` (inline preview `Content-Disposition`, email attachment, frontend download); the internal on-disk storage path (`application_{id}.pdf`) is unaffected since it is never shown to a user. Governs R3.

### Assumptions

- When the text remaining after stripping the Betreff line is blank, the dialog's Message field is left blank rather than synthesizing placeholder text — the backend's own (reworded) fallback body fills it in if the user sends without typing anything.
- Retry after a failed send keeps whatever Subject/Message the user last had in the dialog rather than re-deriving fresh — this preserves the existing unconditional `emailForm.patchValue(result)` behavior, unchanged by this feature.

### Risks & Dependencies

- No automated visual/pixel regression testing exists for generated PDFs in this repo; test scenarios below assert on the Jinja-rendered HTML and on render success/failure, not on rendered PDF appearance. Low risk given the small, mechanical nature of the template change (removing a section and one CSS rule).

---

## Implementation Units

### U1. CV-only PDF template and renderer

- **Goal:** Produce a CV-only PDF, replacing the combined Anschreiben+CV render path.
- **Requirements:** R1, R2. Cites KTD4.
- **Dependencies:** None.
- **Files:**
  - `backend/app/templates/application.html` (edit)
  - `backend/app/services/pdf_service.py` (edit)
  - `backend/tests/services/test_pdf_service.py` (new)
- **Approach:**
  1. Remove the `<section class="cover-letter">` block and its CSS (`.cover-letter`, `.sender-block`, `.recipient-block`, `.date-block`, `.letter-body`) from `application.html`. Keep the `<section class="cv">` block, its CSS, and the `@page` counter footer unchanged, except drop `page-break-before: always` from `.cv` (no longer needed with no preceding page).
  2. Replace `render_application_pdf(cover_letter_text, cv, job_offer) -> bytes` with `render_cv_pdf(cv: TailoredCv) -> bytes` in `pdf_service.py`: same `_env.get_template("application.html")` load and `HTML(...).write_pdf()` conversion, `PdfRenderError` on exception or empty bytes unchanged (KTD4).
  3. Rewrite the module docstring to drop the "bewusst als EIN zusammenhängendes PDF" rationale, which no longer applies.
- **Patterns to follow:** Keep the existing Jinja `Environment`/template-loading and `PdfRenderError` handling exactly as `pdf_service.py` already does it.
- **Test scenarios:**
  - Renders a `TailoredCv` with experiences, education, and skills → returns non-empty PDF bytes without raising.
  - The Jinja-rendered HTML passed to WeasyPrint contains no `cover-letter` markup (assert on the intermediate HTML string, not the compiled PDF bytes).
  - A `TailoredCv` with empty experiences/education/skills still renders without error.
  - WeasyPrint raising during conversion still surfaces as `PdfRenderError` (unchanged contract).
- **Verification:** `cd backend && pytest tests/services/test_pdf_service.py` passes.

### U2. Wire CV-only renderer into generate/update/pdf/send endpoints

- **Goal:** Every PDF read path (generate, update/regenerate, inline preview, download, email) serves or persists CV-only bytes under the renamed filename, and the backend's own default email text stops describing an attached Anschreiben.
- **Requirements:** R2, R3. Cites KTD5.
- **Dependencies:** U1.
- **Files:**
  - `backend/app/api/applications.py` (edit)
  - `backend/tests/api/test_applications.py` (extend)
- **Approach:**
  1. `generate_application` (`POST /generate`) and `update_application` (`PUT /{id}`) call `render_cv_pdf(tailored_cv)` instead of `render_application_pdf(cover_letter_text, cv, job_offer)`; both still persist `pdf_bytes` to `_pdf_path_for(application.id)` unchanged.
  2. `get_application_pdf` (`GET /{id}/pdf`) and `send_application` (`POST /{id}/send`) rename their `Content-Disposition`/`attachment_filename` values from `bewerbung_{id}.pdf` to `lebenslauf_{id}.pdf` (KTD5). `_pdf_path_for`'s on-disk filename (`application_{id}.pdf`) stays as-is.
  3. Reword `send_application`'s default `body_text` boilerplate so it no longer claims "Anschreiben und Lebenslauf" are both enclosed — it references only the attached CV/Lebenslauf.
- **Test scenarios:**
  - `POST /generate` persists CV-only PDF bytes at `application.pdf_path`.
  - `PUT /{id}` with a changed `cover_letter_text` still re-renders the PDF (regression: trigger condition on `cover_letter_text` OR `tailored_cv_json` change is unchanged; only the renderer called changes).
  - `GET /{id}/pdf` responds with `Content-Disposition` filename `lebenslauf_{id}.pdf`.
  - `POST /{id}/send` with a blank `subject`/`message` payload uses the reworded fallback subject/body and attaches with filename `lebenslauf_{id}.pdf`.
  - `POST /{id}/send`'s fallback body text no longer contains the word "Anschreiben".
- **Verification:** `cd backend && pytest tests/api/test_applications.py` passes.

### U3. Betreff-parsing utility (frontend)

- **Goal:** A pure function that splits an Anschreiben text into its Betreff-derived subject and the remaining message body.
- **Requirements:** R4, R5, R6. Cites KTD1.
- **Dependencies:** None.
- **Files:**
  - `frontend/src/app/core/utils/cover-letter.util.ts` (new)
  - `frontend/src/app/core/utils/cover-letter.util.spec.ts` (new)
- **Approach:**
  1. Export `parseBetreff(coverLetterText: string | null | undefined): { subject: string | null; message: string }`.
  2. Match only the first non-empty line of the text against a case-insensitive `Betreff:` label; capture the remainder of that line as `subject`.
  3. `message` is the input with that line (and one immediately-following blank separator line, if present) removed and trimmed. When no Betreff line matches, `subject` is `null` and `message` is the trimmed input unchanged.
  4. Normalize `\r\n` line endings before matching (KTD1: first non-empty line, not strictly physical line 1, so leading blank lines before the Betreff line still match).
- **Test scenarios:**
  - `"Betreff: Bewerbung als X\n\nSehr geehrte..."` → `subject: "Bewerbung als X"`, `message` starts at `"Sehr geehrte..."`.
  - `"betreff: x"` (lowercase) → matches case-insensitively.
  - No Betreff line at all → `subject: null`, `message` equals the trimmed input.
  - One or more leading blank lines before `"Betreff: ..."` → still matches (first non-empty line, not physical line 1).
  - `\r\n` line endings parse the same as `\n`.
  - A Betreff line with no blank-line separator before the next content → only the Betreff line itself is stripped from `message`.
  - `null`/`undefined`/empty-string input → `subject: null`, `message: ''`.
  - Body is empty after stripping the Betreff line → `message: ''`.
- **Verification:** `cd frontend && ng test` passes for `cover-letter.util.spec.ts`.

### U4. Pre-fill send dialog Subject/Message and rename download filename

- **Goal:** The send dialog opens with the Betreff-derived Subject/Message (or the "E-Mail-Text" tab's manual override when present), and the manual download uses the renamed filename.
- **Requirements:** R3, R4, R5, R6, R7. Cites KTD2, KTD3.
- **Dependencies:** U3.
- **Files:**
  - `frontend/src/app/pages/application-editor/application-editor.component.ts` (edit)
  - `frontend/src/app/pages/application-editor/application-editor.component.html` (edit)
  - `frontend/src/app/pages/application-editor/application-editor.component.spec.ts` (extend)
- **Approach:**
  1. In `onOpenSendDialog()`, before building the `dialogRef` data, call `parseBetreff(application()?.cover_letter_text ?? null)` (KTD2: the saved value from `application()`, not `coverLetterForm`'s live value).
  2. Compute a fallback subject mirroring the backend's job-title-based default: `jobOffer()?.title` present → `` `Bewerbung als ${title}` ``, else `"Bewerbung"`.
  3. Seed the dialog's `subject`/`message` from `emailForm`'s current values when non-empty (KTD3: Tab-3 override), else from the derived Betreff subject/message, else the job-title fallback subject / empty message. Evaluate `subject` and `message` independently — a Tab-3 value typed into one field does not suppress derivation for the other (e.g., a manually-typed Subject with an empty Message still gets the Betreff-derived Message).
  4. `onDownloadPdf()`: change `link.download` to `` `lebenslauf_${application.id}.pdf` ``.
  5. Reword the "E-Mail-Text" tab's hint text to state that Subject/Message are normally derived from the Anschreiben's Betreff line, and that anything typed there is used instead.
  6. Leave `dialogRef.afterClosed()` → `emailForm.patchValue(result)` unchanged (Planning Contract Assumptions: retry-after-failure keeps last-used values).
- **Test scenarios:**
  - Tab-3 empty + Anschreiben has a Betreff line → dialog opens with the derived subject and message.
  - Tab-3 has a manually-typed subject → dialog opens with Tab-3's subject, not the derived one.
  - Tab-3 has a manually-typed subject but an empty message, Anschreiben has a Betreff line → dialog opens with Tab-3's subject AND the Betreff-derived message (per-field evaluation, not paired).
  - Anschreiben has no Betreff line + Tab-3 empty → dialog subject shows the job-title-based fallback text.
  - No job offer linked + no Betreff line + Tab-3 empty → dialog subject shows the generic `"Bewerbung"` fallback.
  - `onDownloadPdf()` sets `link.download` to `lebenslauf_{id}.pdf`.
  - Regression: after a failed send, reopening the dialog still shows the previously-confirmed values (unchanged `patchValue` behavior).
  - Regression (R7): `application()?.cover_letter_text` and `coverLetterForm`'s value are unchanged after opening the send dialog — `onOpenSendDialog()` only reads the saved text, never writes to it.
- **Verification:** `cd frontend && ng test` passes for `application-editor.component.spec.ts`.

---

## Verification Contract

| Scope | Command | Applicability |
|---|---|---|
| Backend unit/integration tests | `cd backend && pytest` | All backend units (U1, U2) |
| Frontend unit tests | `cd frontend && ng test` | All frontend units (U3, U4) |
| Filename-rename completeness | `grep -rn "bewerbung_" backend frontend/src` | Must return no matches after U2 and U4 land |

No `release:validate` gate or behavioral skill evaluation applies to this repo/change.

## Definition of Done

- U1-U4 implemented; `pytest` (backend) and `ng test` (frontend) both pass, including every test scenario listed above.
- `grep -rn "bewerbung_" backend frontend/src` returns no matches.
- `pdf_service.py` no longer exposes a `cover_letter_text`/`job_offer`-accepting renderer; only `render_cv_pdf(cv)` remains.
- Manual check: generating or regenerating an application shows a CV-only PDF in the live preview and the downloaded file; opening the send dialog shows the Betreff-derived Subject/Message (or the Tab-3 override); the sent email's attachment is named `lebenslauf_{id}.pdf`.
- No leftover cover-letter markup or CSS (commented out or otherwise) remains in `application.html`.
