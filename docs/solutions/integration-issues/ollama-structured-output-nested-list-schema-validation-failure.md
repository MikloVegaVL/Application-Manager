---
title: "Ollama structured-output validation fails permanently for schemas with nested list[SubModel] fields ($defs/$ref)"
date: 2026-08-18
category: integration-issues
module: "backend/app/services/llm_client.py (generate_structured)"
problem_type: integration_issue
component: assistant
symptoms:
  - "Pydantic ValidationError raised on Ollama structured-output calls for schemas containing a list[SubModel] nested field (JSON schema using $defs/$ref)"
  - "Retrying the identical prompt/schema after a validation failure never resolves the error - unlike an ordinary one-off model mistake"
  - "generate_structured raises LlmValidationError deterministically on the same nested-list field path (e.g. experiences, education) on both the first attempt and the retry"
  - "Ollama-side request timeout (httpx.TimeoutException) was not caught by the ConnectionError handler and produced an unhandled 500 instead of a graceful unavailable error"
root_cause: wrong_api
resolution_type: code_fix
severity: high
related_components:
  - "pdf_parser.py (analyze_cv_text)"
  - "ai_generator.py (generate_application_content)"
  - "profile.py (upload_cv route - related event-loop-blocking fix, secondary)"
tags: [ollama, structured-output, pydantic, json-schema, defs-ref, retry-fallback, llm-integration, constrained-decoding]
---

# Ollama structured-output validation fails permanently for schemas with nested list[SubModel] fields ($defs/$ref)

## Problem

While migrating CV parsing (`analyze_cv_text`) and tailored application generation (`generate_application_content`) off OpenAI onto a locally-hosted Ollama model (native `ollama` Python client v0.6.2, schema-constrained structured output via `client.chat(..., format=<pydantic-json-schema>)`), structured-output generation could fail Pydantic validation in a way where retrying the *identical* prompt/schema never converges. The failure is specific to Pydantic response models containing a `list[SomeSubmodel]` field — any JSON schema that uses `$defs`/`$ref` to describe an array of objects. Both schemas this migration introduced have this shape: `ParsedCvProfile` (`experiences`, `education`) and the CV-content schema nested inside `AiGenerationResult` (`cv_content.experiences`, `cv_content.education`).

This matches a known, open upstream Ollama defect, `ollama/ollama#8444` — an open, unresolved upstream bug where `$defs`-referencing JSON schemas can fail constrained decoding depending on definition ordering. Nothing in this repo claims it was fixed upstream; the mitigation described below is a caller-side workaround, not a wait for an upstream patch.

## Symptoms

- A `pydantic.ValidationError` recurs on the *same* nested-list field path (e.g. `experiences` or `cv_content.experiences`) across repeated generation attempts against an unchanged schema and prompt.
- Retrying does not help: the second failure lands on the identical structural location as the first, which is the tell that this is a schema/decoding-engine issue rather than an ordinary one-off content slip from the model.
- Directly exercised in `backend/tests/services/test_llm_client.py`'s `TestStructuralFailureFallback` class: the first attempt drops `company` from `experiences[0]`, and the retry (which already included the validation error in the prompt) still fails inside `experiences`, just at a different item/field (`experiences[1]` missing `role`).
- Separately, an Ollama-side request timeout (`httpx.TimeoutException`) was not covered by the `ConnectionError` handler and would otherwise propagate uncaught out of the call helper as an unhandled 500.

## What Didn't Work

The initial design was a plain "retry once on schema-validation failure, then fail" policy — a reasonable-sounding cheap safety net for a local model being somewhat more likely to miss a schema than a hosted model. This was codified as an early plan requirement ("the backend retries once ... before surfacing the existing ... failure") with an acceptance example describing "given the Ollama response fails schema validation on both the first attempt and the retry ... the same error type raised today for a hard OpenAI failure ... is raised."

That plain policy does not work for this failure mode: retrying against an *unchanged* nested-list schema just reproduces the same decoding pathology, because the failure is driven by the schema's shape, not by the specific content the model attempts to produce. The correction was made during plan review, before implementation — once it was recognized that a same-schema retry structurally cannot resolve a decoding-engine-level bug tied to the schema shape itself, the plan was revised to add structural-failure detection and a flattened-schema fallback path. The shipped code already implements the corrected design; the naive single-retry-then-fail version was never deployed.

## Solution

The full mechanism lives in `backend/app/services/llm_client.py`.

**Detecting a structural (vs. ordinary) failure.** `_is_nested_list_field` inspects a Pydantic field annotation and returns the item model class if the field is `list[SomeModel]`:

```python
def _is_nested_list_field(annotation: Any) -> type[BaseModel] | None:
    if get_origin(annotation) is not list:
        return None
    args = get_args(annotation)
    if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return args[0]
    return None
```

`_nested_list_field_paths` walks a model's fields recursively — including through nested submodel fields — and collects every field-path tuple whose type is a list of Pydantic models. This lets detection work not just for `ParsedCvProfile.experiences` (top-level) but also for `AiGenerationResult.cv_content.experiences` (nested one level down inside a submodel).

`_is_structural_failure` then compares the `.loc` tuples of two consecutive `ValidationError`s against that set of nested-list paths, and returns true only if both attempts hit the *same* nested-list path:

```python
def _is_structural_failure(
    first_exc: ValidationError, second_exc: ValidationError, model_cls: type[BaseModel]
) -> bool:
    list_paths = _nested_list_field_paths(model_cls)
    if not list_paths:
        return False

    def _hit_paths(exc: ValidationError) -> set[tuple[str, ...]]:
        hits: set[tuple[str, ...]] = set()
        for error in exc.errors():
            loc = tuple(error["loc"])
            for path in list_paths:
                if loc[: len(path)] == path:
                    hits.add(path)
        return hits

    return bool(_hit_paths(first_exc) & _hit_paths(second_exc))
```

A failure on a different or top-level field on the second attempt does *not* set-intersect and is correctly treated as ordinary retry-exhaustion (raises `LlmValidationError` after exactly 2 calls, no third/fallback call).

**Flattening the schema.** `_build_flat_variant` is `@lru_cache`-d and builds a `$ref`-free sibling Pydantic model via `pydantic.create_model`: every `list[SomeModel]` field is replaced with a plain `str` field (the array comes back as a JSON-encoded string instead of a JSON array-of-objects), and nested submodel fields are recursively flattened the same way. Because the resulting schema has no array-of-object construction, its `model_json_schema()` output contains no `$defs`/`$ref` indirection for those fields, sidestepping the decoding bug entirely. `_reconstruct` then walks a validated flat instance back into the original nested shape — parsing each flattened field's JSON string (defensively falling back to `[]` on a decode error or non-list result) and recursively reconstructing nested submodels, before a final `model_cls.model_validate(data)`.

**Sequencing in `generate_structured`:**

1. Attempt 1 against `model_cls`'s real schema. On success, return immediately (happy path is a single call).
2. On a `ValidationError`, retry once with the invalid output *and* the specific validation error appended to the prompt (rather than resending an identical request).
3. On a second `ValidationError`, check `_is_structural_failure`. If false, raise `LlmValidationError` (2 calls total — ordinary retry-exhaustion).
4. If true, build the flattened variant, call once more against the flattened schema, validate, `_reconstruct` back to `model_cls`, and return it (3 calls total). Any validation failure at this stage also raises `LlmValidationError`.

**The separate `httpx.TimeoutException` gotcha.** `_call_chat` explicitly catches three, and only three, exception types around `client.chat(...)`: `ollama.ResponseError`, the builtin `ConnectionError`, and `httpx.TimeoutException` — each normalized to `LlmUnavailableError`. This third clause is not redundant: in the `ollama` 0.6.2 client, `httpx.ConnectError` is re-raised as the builtin `ConnectionError` (unwrapped), but `httpx.TimeoutException` is a distinct, sibling exception hierarchy in `httpx` that the client does **not** catch or wrap at all — without an explicit `except httpx.TimeoutException` clause, an Ollama-side timeout propagates uncaught. The test suite encodes the distinction explicitly, asserting `not isinstance(httpx.TimeoutException("x"), ConnectionError)` (and vice versa) so a test can't accidentally pass via the wrong `except` clause. None of these three exception types trigger a validation retry or fallback — `LlmUnavailableError` is raised immediately on attempt 1, since the retry/fallback machinery above applies only to schema-validation failures, not connectivity failures.

## Why This Works

Per the upstream issue, Ollama's constrained-decoding engine can get stuck when a JSON schema uses `$defs`/`$ref` to describe certain nested structures — specifically arrays of referenced object definitions, which is exactly what `list[SomeSubmodel]` compiles to under Pydantic's `model_json_schema()`. Because the failure is tied to the *schema shape* the constrained decoder is given, not to the specific content the model attempts to produce, resending the same prompt against the same schema (even with a corrective validation-error message appended) reproduces the same decoding pathology — hence the retry landing on the identical nested-list path both times.

Flattening removes the `$ref` indirection for exactly the field types implicated in the bug: a `list[SomeModel]` field becomes a plain `str` field in the schema sent to Ollama, so the schema it has to decode against no longer contains the problematic construct. The model emits the list contents as a JSON-encoded string instead — trivial for constrained decoding — which is then parsed back with `json.loads`. Because `_reconstruct` walks the same `list_fields`/`submodels` maps `_build_flat_variant` recorded, it rebuilds the exact original nested Pydantic shape callers expect. The flattening/reconstruction round-trip is entirely internal to `generate_structured`; callers in `pdf_parser.py`/`ai_generator.py` never see a flat model, only ever `ParsedCvProfile` or `AiGenerationResult` instances.

## Prevention

- **Route new Ollama structured-output call sites through `generate_structured`, not raw `client.chat(format=...)`.** Any new Pydantic response model with a `list[SomeSubmodel]` field carries the same structural-failure risk; `generate_structured` already has the detection + flattened-fallback machinery generically (it walks `model_cls.model_fields` recursively, not hardcoded field names) — a new schema doesn't need new fallback code, just call the shared helper.
- **When catching `ollama` client exceptions, always catch `httpx.TimeoutException` explicitly alongside `ollama.ResponseError` and the builtin `ConnectionError`.** Don't assume `ConnectionError` alone covers request timeouts. If the pinned `ollama` package version ever moves, re-verify this exception-wrapping behavior against the new version's client source before assuming it still holds.
- **Test structural detection at both nesting depths when adding a new nested schema**: a top-level `list[SomeModel]` field, and, if applicable, a `list[SomeModel]` field reachable through an intermediate submodel field. `_nested_list_field_paths` already recurses through submodels to find both, but a regression test per new schema is cheap insurance:

```python
def test_nested_submodel_list_field_also_detected_as_structural(self, mock_client):
    """Nesting one level deeper (AiGenerationResult.cv_content.experiences)."""
    first_invalid = {
        "cover_letter_text": "Anschreiben",
        "cv_content": {
            "summary": "S",
            "experiences": [{"role": "Entwickler"}],
            "education": [],
            "skills": [],
        },
    }
    second_invalid = {
        "cover_letter_text": "Anschreiben",
        "cv_content": {
            "summary": "S",
            "experiences": [
                {"company": "Acme GmbH", "role": "Entwickler"},
                {"company": "Beta AG"},
            ],
            "education": [],
            "skills": [],
        },
    }
    # ... flat_payload fixture with experiences/education as JSON strings ...
    mock_client.chat.side_effect = [
        _response(first_invalid),
        _response(second_invalid),
        _response(flat_payload),
    ]

    result = llm_client.generate_structured(AiGenerationResult, _messages())

    assert isinstance(result, AiGenerationResult)
    assert result.cv_content.experiences[0].company == "Acme GmbH"
    assert mock_client.chat.call_count == 3
```

- **Don't ship a plain "retry once, then fail" policy for local structured-output models without also asking whether a failure could be schema-shape-driven.** This codebase's own planning history is the cautionary example: the original single-retry requirement had to be revised before implementation once it was recognized that a same-schema retry cannot fix a decoding-engine-level bug tied to the schema's own shape — worth checking for during plan/doc review on any future Ollama (or similar locally-hosted constrained-decoding) integration work, rather than discovering it against a real failure in production.

## Related Issues

- Upstream: `ollama/ollama#8444` — open/unresolved as of this writing. The flattened-schema fallback here is a caller-side mitigation, not a fix of the upstream bug; if the pinned Ollama server/model version changes, re-check whether the underlying decoding bug still reproduces.
- `docs/plans/2026-08-17-001-refactor-openai-to-ollama-migration-plan.md` — the plan that specified this retry/structural-fallback contract and records the correction from a plain single-retry policy.
- `docs/residual-review-findings/5498abb.md` (finding #7) references "the OpenAI prompt in `backend/app/services/ai_generator.py`" — that wording is now stale since this migration moved that call to Ollama; the underlying prompt-injection concern itself is unaffected by the provider swap and likely still applies to the Ollama prompt.
