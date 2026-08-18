---
title: OpenAI to Ollama Migration - Plan
type: refactor
date: 2026-08-17
topic: openai-to-ollama-migration
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
deepened: 2026-08-17
---

# OpenAI to Ollama Migration - Plan

## Goal Capsule

- **Objective:** Replace OpenAI/GPT-4o with a locally-run Ollama model for CV-import parsing and tailored application generation, removing ongoing OpenAI API cost entirely.
- **Product authority:** This session's brainstorm dialogue. `application-manager` is a single-user personal tool (per `README.md`); there are no external stakeholders to align with.
- **Open blockers:** None.
- **Product Contract preservation:** Unchanged. Planning added a Planning Contract, Implementation Units, Verification Contract, and Definition of Done. R7's retry mechanism is refined (the retry prompt now includes the validation error, per Assumption A2) and extended with KTD5's structural-failure fallback (new AE4). AE1 is unchanged; AE2 is scoped to the non-structural case (see AE4 for the structural-fallback path).

## Product Contract

### Summary

Replace OpenAI/GPT-4o with a locally-run Ollama model for both CV-import parsing (`analyze_cv_text`) and tailored application generation (`generate_application_content`), eliminating ongoing API cost. Ollama runs as a new `docker-compose.yml` service; the backend integrates via Ollama's native client using schema-constrained JSON output rather than free-form JSON mode.

### Problem Frame

Both AI-assisted features in the app call OpenAI's Chat Completions API per request today: `backend/app/services/pdf_parser.py` (`analyze_cv_text`) sends the extracted CV text to GPT-4o once per profile import, and `backend/app/services/ai_generator.py` (`generate_application_content`) sends the profile and job offer to GPT-4o once per generated application. Every CV imported and every application generated incurs an OpenAI API charge, with no local, no-cost alternative available.

### Key Decisions

- **Full replacement, no OpenAI fallback.** Cost elimination is the goal; keeping OpenAI as an automatic or manual fallback keeps the cost exposure the migration is meant to remove. Governs R3.
- **Ollama as a new Docker Compose service, not a native host install.** Keeps `docker compose up` self-contained for anyone running the stack, with no separate install step outside Docker. Governs R4.
- **Native Ollama client with schema-constrained output, not the OpenAI SDK against Ollama's compatible endpoint.** A small amount of extra client wiring buys materially better JSON-validity odds from a smaller local model than free-form JSON mode would. Governs R6, R7.
- **Retry once on schema-validation failure, then fail.** A local model is more likely to occasionally miss the schema than GPT-4o was; one retry is a cheap safety net without adding open-ended retry complexity. Governs R7 (KTD5 layers one additional attempt on top of this for failures that look structural, not counted as part of the retry).
- **Manual spot-check is the quality bar, not a formal regression benchmark.** Proportionate to a cost-driven, single-user tool — ship once the pipeline works correctly, judge output quality by hand against a few real CVs and job offers, and tune from there. Governs the Success Criteria below.
- **Keep CV-import's immediate-persist behavior unchanged** *(session-settled: user-directed — chosen over adding a review-before-save gate before parsed CV data is written to the DB: keeps this migration scoped to the provider swap; the user already accepted a manual-spot-check quality bar as sufficient, and the profile stays editable afterward same as today)*. Governs R2.

### Requirements

**Provider replacement**

- R1. Tailored cover-letter and CV-content generation (current `generate_application_content` behavior) runs on a locally-run Ollama model instead of OpenAI, preserving the existing no-hallucination and JSON-schema-adherence rules already encoded in its system prompt.
- R2. CV PDF import (current `analyze_cv_text` behavior) parses into a structured profile using the same local Ollama model path; the deterministic PDF text extraction step (`pypdf`, in `extract_text_from_pdf`) is unchanged, and parsed data continues to persist immediately (no new review gate).
- R3. No OpenAI dependency remains once the migration lands: the `openai` package and the `OPENAI_API_KEY` / `OPENAI_MODEL` config are fully removed, with no OpenAI fallback path.

**Deployment and configuration**

- R4. Ollama runs as a new service in `docker-compose.yml`, reachable by the backend over the Docker network, with no native Ollama install required on the host.
- R5. The Ollama model is configurable, following the same pattern `OPENAI_MODEL` used today, so the model can be swapped without a code change.

**Reliability**

- R6. LLM responses are validated against a JSON schema constrained at generation time, not only checked after the fact.
- R7. When a response fails schema validation, the backend retries once (with the validation error appended to the prompt) before surfacing the existing `PdfParsingError` / `CvAnalysisError` / `ApplicationGenerationError` failure — except when the retry's failure looks structural rather than content-related (see KTD5), where one additional attempt against a flattened schema variant precedes the failure.

**User-facing consistency**

- R8. User-facing copy naming the AI provider — currently "GPT-4o" on the profile upload page (`frontend/src/app/pages/profile/profile.component.html`) — no longer references OpenAI or GPT-4o.

### Acceptance Examples

- AE1. **Covers R7.** Given the Ollama response fails schema validation on the first attempt, When the backend retries once and the second response validates, Then the retried result is returned successfully with no error surfaced.
- AE2. **Covers R7.** Given the Ollama response fails schema validation on both the first attempt and the retry, and the failure does not look structural (per KTD5), When both attempts are exhausted, Then the same error type raised today for a hard OpenAI failure (`PdfParsingError` / `CvAnalysisError` / `ApplicationGenerationError`) is raised.
- AE3. **Covers R3.** Given Ollama is unreachable, unconfigured, or times out, When a CV is uploaded or an application is generated, Then the request fails with a clear availability/configuration error — there is no fallback attempt to OpenAI and no retry (retry applies only to schema-validation failures, per R7).
- AE4. **Covers R6, R7.** Given the first attempt and the retry both fail schema validation on the same nested-list field path (the structural signal per KTD5), When the flattened-schema fallback attempt succeeds, Then the reconstructed nested result is returned successfully with no error surfaced.

### Success Criteria

- A manual spot-check against a handful of real CVs and job offers produces cover letters and parsed profiles judged usable in German — not measured against a formal benchmark or held to zero regression from the prior GPT-4o output.
- No OpenAI package, API key, or API call remains anywhere in the codebase after the migration.

### Scope Boundaries

- Formal quality benchmarking is out of scope — a manual spot-check is the bar (see Success Criteria), not a non-regression suite.
- A review-before-save gate for parsed CV data is out of scope for this migration (see the CV-import Key Decision above).

### Dependencies / Assumptions

- Assumes Ollama can run in the target Docker environment; no GPU requirement was discussed, so response latency on CPU-only hardware may be materially slower than GPT-4o was. Accepted as a trade-off, not a blocker, since the quality bar is a manual spot-check rather than a latency target. (See Assumption A3 in the Planning Contract for a related correctness fix this trade-off requires.)
- The existing system prompts (German-language output, no-hallucination rules, JSON output shape) carry over unchanged as the starting point for the new model; any retuning needed for the different model happens as part of the manual spot-check.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Ollama Docker Compose service mirrors the existing `db` service pattern for its healthcheck-gated startup, not its host-port exposure.** `ollama/ollama:latest` image, a named volume for model persistence, `restart: unless-stopped`; `backend`'s `depends_on` gates on `ollama: condition: service_healthy`, the same mechanism already used for `db`. Unlike `db`, the service does not publish a host port — the base Ollama HTTP API has no authentication, so it stays reachable only over the internal Docker network by `backend`. The healthcheck runs `ollama list` (the base image has no `curl` for an HTTP probe) checking for the configured model present, with a `start_period` and retry budget sized for a multi-gigabyte first-time model pull — `db`'s Postgres-readiness timing (~50 seconds total) is too short for that. Governs R4.
- KTD2. **Ollama config replaces the OpenAI block one-for-one in `backend/app/core/config.py`.** `OLLAMA_BASE_URL` (default `http://ollama:11434`), `OLLAMA_MODEL` (configurable; see Assumption A1 for the default), `OLLAMA_TIMEOUT_SECONDS` (default `120.0`, mirroring the existing `JOB_SEARCH_DEADLINE_SECONDS` float-timeout idiom). `backend/requirements.txt` drops `openai` and adds `ollama` pinned to the version KTD3/KTD4's exception-handling behavior was verified against (`ollama==0.6.2`, or a narrow compatible range) — a deliberate exception to the file's otherwise-unpinned convention, since an unrelated version bump could silently change how the client wraps timeouts/connection errors and invalidate KTD3/KTD4's classification. Governs R3, R5.
- KTD3. **A connection failure or request timeout is treated identically to today's "unreachable" failure path** — same exception raised, no new state — since local-inference latency is an already-accepted trade-off, not a new failure class to design around. This requires catching three distinct exception types, not two: `ollama.ResponseError`, the builtin `ConnectionError` (Ollama's client re-raises `httpx.ConnectError` as this, unwrapped), and `httpx.TimeoutException` — verified against `ollama` 0.6.2's client source that timeouts are a sibling of connection errors in `httpx` and are **not** caught or wrapped by the `ollama` client at all; treating "timeout" as covered by the `ConnectionError` catch alone would leave it unhandled. `httpx` is already a direct dependency, so no new package is needed. Governs R3 (see AE3).
- KTD4. **Ollama error handling follows the existing per-service local-exception convention** (no shared exception hierarchy visible to API consumers). Catch `ollama.ResponseError`, the builtin `ConnectionError`, and `httpx.TimeoutException` narrowly (see KTD3), log, and re-raise as the existing `PdfParsingError` / `CvAnalysisError` / `ApplicationGenerationError`. Governs R1, R2, R3, R7.
- KTD5. **Nested-schema generation carries a known upstream reliability risk.** Both migrated schemas (`ParsedCvProfile`, and the CV-content schema inside `AiGenerationResult`) nest lists of sub-models. Ollama has an open, unresolved bug (ollama/ollama#8444) where `$defs`-referencing JSON schemas can fail constrained decoding depending on definition ordering. Mitigation: verify generation against the real configured model and schema before relying on it; if the failure reproduces and looks structural (not a one-off content mistake), fall back to a flattened (non-nested) schema variant for the `format` parameter and reconstruct the nested Pydantic model from the flat result programmatically. **"Looks structural" is operationalized as:** the retry (which already includes the validation error, per A2) fails validation again on the same nested-list field path (`experiences`, `education`, or their equivalent in the CV-content schema) as the first attempt — repeated failure at the identical nested location despite explicit error feedback is the structural signal. A validation failure on a different or top-level field on the second attempt is ordinary retry-exhaustion (R7/AE2), not structural, and does not trigger the fallback. Governs R6, R7 (see AE4).
- KTD6. **Client construction, the schema-constrained call, the A2 retry loop, and KTD5's fallback are implemented once in a shared helper (U7) rather than duplicated between `pdf_parser.py` and `ai_generator.py`.** Both services need the exact same mechanism; duplicating a retry/fallback loop risks the two copies drifting apart. Each call site still catches the helper's own internal exceptions and raises its existing local exception type, preserving KTD4's no-shared-error-surface property. Governs R6, R7.

### Assumptions

*The four items below were left open by the brainstorm or surfaced by planning-time research; they were not confirmed interactively this run (pipeline mode) and are recorded here as the agent's best-grounded defaults, flagged for review rather than treated as settled.*

- A1. **Default Ollama model: `qwen2.5:7b-instruct`.** Best JSON-schema-adherence / CPU-feasibility balance found in research, over Llama 3.1's stronger raw German fluency. Configurable via `OLLAMA_MODEL` (KTD2) — this is a starting default, not a hard requirement.
- A2. **Retry-on-validation-failure includes the prior invalid output and the specific validation error in the retry prompt**, rather than resending an identical request. Research found this is the standard, materially more effective pattern for local-model structured output. Stays within R7's "one retry, then fail" contract and AE1/AE2.
- A3. **The blocking-event-loop issue this migration would otherwise introduce is treated as in-scope technical-correctness work, not deferred — scoped to `profile.py` only.** Verified against the actual route signatures: `upload_cv` is genuinely `async def` and calls the LLM client synchronously inside it — invisible with GPT-4o's low latency, but this would freeze the whole backend process for the full call duration under local CPU inference. `generate_application` (the application-generation route) is already a plain sync `def`, so FastAPI already dispatches it through its own automatic threadpool — it was never at risk and needs no change. Fix: convert `upload_cv` to a plain sync `def`, matching every other route in the touched surface (`generate_application`, `search_jobs`, `save_job`, `get_job`), rather than wrapping it in `run_in_threadpool` — the codebase has no existing `run_in_threadpool` usage, and matching the established sync-`def` idiom is the smaller change (see U5).
- A4. **The Ollama service auto-pulls its configured model at container startup** via a compose-level startup wrapper, gated by the healthcheck, rather than requiring a documented manual `ollama pull` step. Consistent with the brainstorm's own Key Decision that the stack stay self-contained with no separate install step.

### Risks & Dependencies

- **Risk:** Ollama's `$defs`/`$ref` bug (ollama/ollama#8444) is open and unresolved upstream as of this writing; nested-schema generation reliability is not guaranteed on any given Ollama/model version. Mitigation: KTD5.
- **Risk:** Local CPU inference latency is materially higher than GPT-4o's. Already an accepted product trade-off (see origin Dependencies/Assumptions); A3 addresses the correctness issue this trade-off exposes in the current request-handling code.
- **Risk:** Worst-case per-request latency now spans up to three sequential model calls (initial attempt, A2's validation-error retry, and KTD5's structural-failure fallback), each individually eligible for the full `OLLAMA_TIMEOUT_SECONDS`. A single CV upload or application-generation request can take several minutes in the worst case. Accepted as an extension of the already-accepted CPU-latency trade-off, not a new blocker.
- **Dependency:** The `ollama` PyPI package and the `ollama/ollama` Docker image are new dependencies; no other new external dependencies are introduced.
- **Pre-existing, out-of-scope risk (carried forward, not introduced by this migration):** scraped job-description text flows into the generation prompt without sanitization (`docs/residual-review-findings/5498abb.md`). This applies equally regardless of which LLM is called and is not this migration's to fix.

### Sources & Research

- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs, https://ollama.com/blog/structured-outputs
- `$defs`/`$ref` ordering bug: https://github.com/ollama/ollama/issues/8444 (open); related: https://github.com/ollama/ollama/issues/8063
- `ollama` Python package source (`ollama/_client.py`, `ollama/_types.py`), version 0.6.2 — client/exception shape backing KTD2/KTD4; confirms `httpx.TimeoutException` is not caught or wrapped by the client, only `httpx.ConnectError` (backing the KTD3 correction)
- Repo route signatures: `backend/app/api/profile.py` (`upload_cv`, genuinely `async def`) and `backend/app/api/applications.py` (`generate_application`, plain sync `def`, already auto-threadpooled by FastAPI) — backing A3's corrected scope and U5
- Retry-with-validation-error pattern: Instructor's Ollama integration (https://python.useinstructor.com/integrations/ollama/) — backing A2
- Repo patterns: `docker-compose.yml` (`db` service — backing KTD1), `backend/app/core/config.py` (`Settings` shape, `JOB_SEARCH_DEADLINE_SECONDS` — backing KTD2), `backend/app/services/mail_service.py` and `pdf_parser.py`/`ai_generator.py` (local-exception convention — backing KTD4)

---

## Implementation Units

### U1. Add Ollama as a Docker Compose service

- **Goal:** Stand up a local Ollama runtime reachable by the backend, with the configured model available before the backend starts serving requests that need it.
- **Requirements:** R4. KTD1, A4.
- **Dependencies:** None.
- **Files:** `docker-compose.yml`, a new startup-wrapper script (e.g. `docker/ollama-entrypoint.sh`).
- **Approach:**
  1. Add an `ollama` service per KTD1 — `ollama/ollama:latest` image, named volume for model persistence, `restart: unless-stopped`. No host port is published.
  2. Add the `ollama list`-based healthcheck from KTD1, sized (`start_period`, retries) for a multi-gigabyte first-time model pull rather than `db`'s Postgres-readiness timing.
  3. Add a startup wrapper (command/entrypoint override) that pulls the configured model before the healthcheck reports healthy, per A4.
  4. Gate `backend`'s `depends_on` on `ollama: condition: service_healthy`, mirroring the existing `db` gating.
- **Patterns to follow:** the `db` service block in `docker-compose.yml` for healthcheck/volume/restart shape.
- **Test scenarios:** Test expectation: none -- infrastructure/config unit with no application code; proven by the Verification Contract's compose smoke check, not a unit test.
- **Verification:** `docker compose up` brings `ollama` to healthy before `backend` starts; a manual request against the running backend reaches Ollama successfully.

### U2. Replace OpenAI config with Ollama config

- **Goal:** Swap `OPENAI_API_KEY` / `OPENAI_MODEL` for the Ollama equivalents and remove the `openai` dependency.
- **Requirements:** R3, R5. KTD2.
- **Dependencies:** U1.
- **Files:** `backend/app/core/config.py`, `backend/.env.example`, `backend/requirements.txt`.
- **Approach:** Replace the `# --- OpenAI / LLM ---` block with `# --- Ollama / LLM ---` per KTD2's field list and defaults. Remove `openai` from `requirements.txt`; add `ollama==0.6.2` (pinned, per KTD2). Mirror the same fields in `.env.example`.
- **Patterns to follow:** the existing `Settings` class shape; the `JOB_SEARCH_DEADLINE_SECONDS` float-timeout idiom.
- **Test scenarios:** Test expectation: none -- pure config/dependency change, exercised indirectly by U3/U4's tests.
- **Verification:** `Settings()` loads without error with only Ollama env vars set; `openai` is no longer installed or importable in the backend container.

### U7. Extract a shared Ollama call helper

- **Goal:** Implement client construction, the schema-constrained call, the retry-with-validation-error loop, and the nested-schema fallback once, so `pdf_parser.py` and `ai_generator.py` consume one mechanism instead of duplicating it (KTD6).
- **Requirements:** R6, R7. KTD2, KTD3, KTD4, KTD5, KTD6, A2.
- **Dependencies:** U1, U2.
- **Files:** `backend/app/services/llm_client.py` (new), `backend/tests/services/test_llm_client.py` (new).
- **Approach:**
  1. Define a function (e.g. `generate_structured(model, schema, messages, ...)`) that constructs `ollama.Client(host=settings.OLLAMA_BASE_URL, timeout=settings.OLLAMA_TIMEOUT_SECONDS)`, calls `chat(model=model, format=schema, messages=messages)`, and validates the response against the given Pydantic model.
  2. On a validation failure, retry once per A2 — append the invalid output and the validation error to the retry prompt, then validate again.
  3. On a second validation failure that looks structural (not a one-off content mistake), apply KTD5's fallback: retry once more against a flattened (non-nested) schema variant, then reconstruct the original nested Pydantic shape from the flat result.
  4. Catch `ollama.ResponseError`, the builtin `ConnectionError`, and `httpx.TimeoutException` per KTD3/KTD4.
  5. Raise a small set of helper-local exceptions (e.g. one for "validation failed after retries," one for "unavailable" covering the three exception types above) — these never reach API consumers directly; each call site (U3, U4) catches them and raises its own existing local exception type, preserving KTD4's no-shared-error-surface property.
- **Execution note:** Verify the schema-constrained call actually works against the real configured model and both target schemas before trusting the fallback path is even needed (KTD5) — exploratory verification, not a unit test, worth doing before this unit is considered done.
- **Patterns to follow:** the guard-clause/logging style already used in `pdf_parser.py` / `ai_generator.py`; no direct precedent exists for the helper module itself, since this is new shared infrastructure.
- **Test scenarios:**
  - Happy path: a schema-conforming response on the first attempt returns validated content.
  - Retry success: the first response fails validation, the retried call (with the validation error appended) succeeds. Covers AE1.
  - Retry exhausted, non-structural: both attempts fail validation with no structural signal, the "validation failed" exception is raised. Covers AE2.
  - Structural failure with fallback: simulate KTD5's failure mode (repeated validation failure on the same nested-list field path) and confirm the flattened-schema retry is attempted and its result is correctly reconstructed into the nested shape. Covers AE4.
  - Connection failure: a mocked client raises the builtin `ConnectionError`, the "unavailable" exception is raised.
  - Timeout: a mocked client raises `httpx.TimeoutException`, the "unavailable" exception is raised — a distinct code path from `ConnectionError` per KTD3, tested separately. Covers AE3.
- **Verification:** the new test file passes in isolation; U3 and U4 can each be implemented as a thin call into this helper.

### U3. Migrate CV parsing (`analyze_cv_text`) to Ollama

- **Goal:** `analyze_cv_text` produces `ParsedCvProfile` via the shared Ollama helper instead of OpenAI.
- **Requirements:** R2, R6, R7. KTD6.
- **Dependencies:** U1, U2, U7.
- **Files:** `backend/app/services/pdf_parser.py`, `backend/tests/services/test_pdf_parser.py` (new).
- **Approach:**
  1. Call U7's helper with `ParsedCvProfile`'s JSON schema and the existing prompt construction (system prompt content carries over unchanged, per the origin's Dependencies/Assumptions).
  2. Catch the helper's "validation failed" and "unavailable" exceptions and translate both to `CvAnalysisError`, matching today's error shape.
- **Patterns to follow:** the existing `pdf_parser.py` guard-clause/exception shape.
- **Test scenarios:**
  - Happy path: the helper returns validated content; `analyze_cv_text` returns the expected `ParsedCvProfile`.
  - Helper raises "validation failed" -> `CvAnalysisError` is raised. Covers AE2.
  - Helper raises "unavailable" -> `CvAnalysisError` is raised. Covers AE3.
  - Edge case: extracted text at or over `_MAX_INPUT_CHARS` is still truncated before calling the helper, unchanged from today.
- **Verification:** the new test file passes; a manual CV upload against the running stack returns a plausible parsed profile.

### U4. Migrate application generation (`generate_application_content`) to Ollama

- **Goal:** `generate_application_content` produces cover-letter and tailored CV content via the shared Ollama helper instead of OpenAI.
- **Requirements:** R1, R6, R7. KTD6.
- **Dependencies:** U1, U2, U7.
- **Files:** `backend/app/services/ai_generator.py`, `backend/tests/services/test_ai_generator.py` (new).
- **Approach:** Mirrors U3's approach applied to `AiGenerationResult` / `TailoredCv` — call U7's helper with the CV-content schema and the existing `_build_user_prompt` construction, then translate the helper's exceptions to `ApplicationGenerationError`.
- **Patterns to follow:** U3 (same shape, applied to this service).
- **Test scenarios:** same shape as U3 — happy path; helper "validation failed" -> `ApplicationGenerationError` (Covers AE2); helper "unavailable" -> `ApplicationGenerationError` (Covers AE3); `_MAX_JOB_DESCRIPTION_CHARS` truncation boundary unchanged.
- **Verification:** the new test file passes; a manual "generate application" request against the running stack returns a plausible cover letter and CV content.

### U5. Fix `upload_cv`'s blocking Ollama call

- **Goal:** Prevent the CPU/network-bound Ollama call from freezing the ASGI event loop in the one route that's genuinely at risk.
- **Requirements:** supports R2 (technical-correctness necessity introduced by the latency change; no product-level requirement change). A3.
- **Dependencies:** U3.
- **Files:** `backend/app/api/profile.py` only — `applications.py` is out of scope for this unit; its route is already a plain sync `def` and was never at risk (see A3).
- **Approach:** Convert `upload_cv` from `async def` to a plain sync `def`, matching every other route in the touched surface (`generate_application`, `search_jobs`, `save_job`, `get_job`), which already rely on FastAPI's automatic threadpool dispatch for sync handlers. Swap `await file.read()` for the sync `file.file.read()`. No new concurrency idiom introduced.
- **Test scenarios:** Test expectation: none -- behaviorally a no-op from the caller's perspective (same inputs/outputs); verify manually that an unrelated endpoint (e.g. a health check or job listing) responds while a slow CV-parse call is in flight.
- **Verification:** the manual concurrent-request check passes; existing route behavior (status codes, response bodies) is unchanged.

### U6. Remove remaining OpenAI/GPT-4o references

- **Goal:** Satisfy R8 and the Success Criteria's "no OpenAI ... anywhere in the codebase."
- **Requirements:** R8.
- **Dependencies:** None.
- **Files:** `frontend/src/app/pages/profile/profile.component.html`, `backend/app/services/pdf_parser.py` (module docstring), `backend/app/services/ai_generator.py` (module docstring), `backend/app/schemas/generation.py` (docstring), `backend/app/api/profile.py` (docstring), `README.md`, `docker-compose.yml` (comment).
- **Approach:** Mechanical text replacement only, no behavior change. Frontend copy stops naming a specific provider or model (e.g., replace "GPT-4o extrahiert..." with neutral phrasing — exact wording is the implementer's call). README's tech-stack line and setup instructions updated to reference Ollama instead of OpenAI.
- **Test scenarios:** Test expectation: none -- copy/documentation only.
- **Verification:** a repo-wide search for "OpenAI" / "GPT-4o" outside this plan file and other historical/residual docs returns nothing.

---

## Verification Contract

- `cd backend && pytest tests/services/test_llm_client.py tests/services/test_pdf_parser.py tests/services/test_ai_generator.py -v` — new unit tests (U7, U3, U4) pass.
- `cd backend && pytest` — full backend suite passes with no regressions.
- `docker compose up --build` — `ollama` reaches healthy and `backend` starts only after; manually upload a CV and generate an application against the running stack.
- `grep -i openai backend/requirements.txt` returns nothing.
- `grep -ril "gpt-4o\|openai" backend/app frontend/src README.md docker-compose.yml` returns nothing.

## Definition of Done

- All implementation units (U1, U2, U7, U3, U4, U5, U6) are complete and their test scenarios pass.
- `docker compose up` brings the full stack up with `ollama` healthy and the configured model available, with no manual setup step beyond `docker compose up`.
- No `openai` package, API key, or API call remains in the codebase (R3, R8, Success Criteria).
- A manual spot-check against a real CV and a real job offer produces usable German output (per the origin's own quality bar).
- Any exploratory dead-end from KTD5's schema-verification step (e.g., an unused flattened-schema code path, if the nested schema turned out to work fine as-is) is removed, not left in the diff.
