# Residual Review Findings

Source: `ce-code-review mode:agent` on branch `feat/cv-preview-templates`
(base `develop`), 2026-09-12. Applied fixes were committed with the
implementation; the items below were deliberately not applied and remain as
known residuals.

## Residual Review Findings

- P2 (manual) — `backend/app/schemas/master_profile.py`: `template_id` write schemas stay `str | None`, so `PATCH`/`PUT /profile` can persist an unrenderable id (e.g. `modern`) and a Builder save can race the picker normalization. Deferred by plan KTD10: the migration plus the frontend picker normalization cover the only known legacy value; tightening the write schema is a separate product decision.
- P2 (manual) — `backend/app/services/pdf_service.py`: dropping `modern` from `CvTemplateId` returns 422 for a client still posting it, with no server-side legacy alias. This is the intended behavior per plan R1/KTD5 (the test `test_render_rejects_legacy_modern_template_id` pins it); a deprecation alias was not added.
- P3 (manual) — `backend/app/templates/cv/classic.html`, `template-1.html`: a real education entry with a blank `field_of_study` shows no placeholder for that sub-field in preview. Low value and arguably misleading (it would fabricate a field of study for real data); deferred.
- P3 (advisory) — `backend/app/api/cv_builder.py`: the preview PDF carries no visible "Vorschau – Beispieldaten" marker; it is distinguished only by muted styling. Tracked as an Open Question in the plan (`docs/plans/2026-09-12-001-feat-cv-preview-templates-plan.md`), deferred to implementation.
- P3 (advisory) — `frontend/src/app/core/models/master-profile.model.ts`: `CvRenderPayload.template_id` remains `string` rather than a `'classic' | 'template-1'` union mirroring the backend Literal; runtime guard is `canRender()`.
- P3 (advisory) — `backend/tests/services/test_pdf_service.py`: the canonical-section assertion includes `Profil`, which for `classic` is now preview-gated and so is not tautological; retained as-is.
