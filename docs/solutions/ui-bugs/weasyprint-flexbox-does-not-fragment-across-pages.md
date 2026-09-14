---
title: "WeasyPrint does not fragment a row flexbox across pages - use display: table for multi-page two-column layouts"
date: 2026-09-12
category: ui-bugs
module: "CV PDF rendering (WeasyPrint templates, cv-builder preview/export)"
problem_type: ui_bug
component: tooling
symptoms:
  - "Template 1's generated CV shows only the sidebar (Contact/Skills) on page 1; the name, profile and experience sections all start on page 2"
  - "The candidate's name - the first thing that should appear on the CV - is pushed to the second page"
  - "The defect only appears with a full profile whose sidebar content exceeds one page (42 un-grouped skills); short profiles render correctly"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
related_components:
  - "backend/app/templates/cv/template-1.html"
  - "backend/app/services/pdf_service.py (render_cv_pdf)"
  - "backend/tests/services/test_pdf_service.py (TestMultiPageFragmentation)"
tags: [weasyprint, css, flexbox, pagination, pdf, cv-builder, layout]
---

# WeasyPrint does not fragment a row flexbox across pages

## Problem

The CV builder's Template 1 rendered the entire main column - the candidate's
name, profile and experience - on page 2, while page 1 held only the sidebar.
The first page of the generated PDF looked blank apart from the Contact/Skills
column, and the name that should head the document appeared a page later.

## Symptoms

- Rendering the real `Thomas Tritscher` profile (42 skills, no categories)
  through `render_cv_pdf(template_id="template-1", ...)` produced two pages:
  page 1 contained only `KONTAKT`/`SKILLS`, page 2 contained
  `THOMAS TRITSCHER`/`PROFIL`/`BERUFSERFAHRUNG`.
- The same profile rendered with `template_id="classic"` put the name on
  page 1 - the bug was specific to the flex-based template.
- Short profiles (the preview sample skeleton) rendered fine on one page, so
  the defect only surfaced once sidebar content exceeded one page.

## What Didn't Work

- `min-height: 100%` on the flex container was the first suspect, but a
  minimal reproduction showed WeasyPrint 69.0 fragments
  `display:flex` and `display:flex; min-height:100%` identically - removing
  the `min-height` did not change the page-1/2 split.
- Blaming the template content (the un-grouped 42-skill list) was a symptom,
  not the cause: the skill list only made the sidebar tall enough to expose
  the layout engine's fragmentation behavior.

## Solution

Replace the page-spanning two-column flex layout with a table layout in
`backend/app/templates/cv/template-1.html`:

```css
/* before */
.cv { display: flex; min-height: 100%; }
.sidebar { width: 62mm; ... }
.main { flex: 1; ... }

/* after */
.cv { display: table; width: 100%; }
.sidebar { display: table-cell; width: 62mm; vertical-align: top; ... }
.main { display: table-cell; vertical-align: top; ... }
```

The regression test renders a profile whose sidebar (60 languages + 40
education entries) is taller than one page and asserts the name is on page 1
(`backend/tests/services/test_pdf_service.py`, `TestMultiPageFragmentation`).

Minimal isolation of the behavior:

| layout | page 1 contains the name? |
|--------|---------------------------|
| `.cv { display: flex }` + `.main { flex: 1 }` | no |
| `.cv { display: table }` + `table-cell` columns | yes |

## Why This Works

WeasyPrint fragments a row flex container by laying out its flex items
sequentially across pages. When the first item (`.sidebar`) overflows page 1,
the second item (`.main`, which holds the name) is placed on the next page
instead of continuing beside the sidebar on page 1 - so the main column
appears to "start on page 2". A `table`/`table-cell` layout is fragmented
correctly: both cells begin on page 1, and whichever is taller continues onto
subsequent pages while the other column's background/box is painted per
fragment.

This is a renderer capability boundary, not a CSS mistake - `display: flex`
is valid CSS, but multi-page fragmentation of a row flex container is not
supported the way the two-column CV layout needs.

## Prevention

- For any paginated two-column layout rendered by WeasyPrint, use
  `display: table` + `display: table-cell` rather than a row flexbox. Keep the
  `display: flex` variant only for content guaranteed to fit on a single page.
- Test layout templates against content that actually exceeds one page. The
  preview sample skeleton is short and hid this bug; the regression test
  deliberately inflates sidebar content past a page boundary.
- Assert on the rendered PDF, not just the intermediate HTML: read the first
  page's extracted text and assert the identity/header content is present.
  HTML-level assertions cannot catch a page-fragmentation defect.
- If a two-column template must use flex for some other reason, verify the
  generated page count and per-page text before shipping.

## Related Issues

- No prior `docs/solutions/` entry covered WeasyPrint fragmentation; the
  closest is `docs/solutions/developer-experience/stale-docker-image-and-squatted-dev-port-mimic-code-bugs.md`
  (also a case of an environment/tooling behavior mimicking a code bug), but
  the mechanism is unrelated.
- `docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md` introduced the
  WeasyPrint/Jinja2 render pipeline and the `classic`/`template-1` templates.
