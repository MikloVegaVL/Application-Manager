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
