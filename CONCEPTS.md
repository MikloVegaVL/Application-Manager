# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## AI Structured Output

### Structural failure
A schema-validation failure on AI-generated structured output that recurs at the identical location across a retry against an unchanged schema, distinguishing it from an ordinary one-off content mistake the model would correct on retry. A structural failure signals that the failure is driven by the shape of the schema itself rather than by the specific content requested, so it is not expected to resolve through further retries against that same schema.

### Flattened-schema fallback
The mitigation applied once a Structural failure is detected: the AI is asked to answer against a temporary, indirection-free variant of the response schema instead of the original one. The answer is validated against that variant and then reconstructed back into the original schema's shape before being returned to the caller, so callers never see the temporary variant.

## CV Builder

### Berufsbezeichnung
The optional job title shown beneath the profile name in a CV template, set independently of any experience entry's `role` (which is a position held at one employer).

### Skill category
The domain a skill belongs to, used to group skills into compact sections in a rendered CV instead of listing every skill individually. A skill without a category falls into a catch-all group, so grouping never drops a skill.

## Job Search

### Applied
A saved job offer is considered applied: saving creates a draft application immediately, so "saved", "on the Applications page", and "applied" describe the same set of job offers. A job offer stops being applied only when its application is deleted, which also removes the job offer.

## Portal Auto-Fill

### Action needed
The paused state of a portal auto-fill run, raised on an Application when the agent hits a captcha, a form field it can't map with confidence, or the mandatory pre-submit confirmation. Distinct from any `ApplicationStatus` value; cleared only when the user resumes the run from the app.

### Run outcome
The single explicit state a portal auto-fill run ends in — submitted, needs-you, or blocked-with-a-reason — produced through one shared contract every portal agent uses, rather than per-agent ad-hoc status values. A run always ends in exactly one run outcome.

### Auto-submit policy
The rule deciding whether a run may submit without human confirmation. When it does not permit submission, the run pauses as Action needed; the user can require confirmation for every submit, which preserves the unconditional pre-submit pause.
