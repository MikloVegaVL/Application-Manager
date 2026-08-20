---
title: "Two Ollama models (CV-parsing and application-generation) could be resident in memory simultaneously, risking Docker VM memory exhaustion"
date: 2026-08-20
category: performance-issues
module: "backend/app/services/llm_client.py (_call_chat / generate_structured)"
problem_type: performance_issue
component: assistant
symptoms:
  - "CV upload -> AI-analyze -> auto-fill profile flow was slow and unreliable when a cover-letter/application-generation request had recently used Ollama"
  - "`ollama ps` inside the Ollama container showed qwen2.5:3b-instruct (CV parsing) and qwen2.5:7b-instruct (application generation) both loaded simultaneously, each at 100% CPU"
  - "`docker stats` showed the Ollama container consuming 6.141GiB of the 7.749GiB total shared Docker Desktop VM memory budget (79.24%), a budget also shared by the Postgres, backend, and frontend containers"
  - "Memory usage only dropped to 27.96% (2.167GiB/7.749GiB) once the 7b model's Ollama-default 5-minute idle keep-alive expired and it unloaded on its own"
  - "No coordination existed between pdf_parser.py's CV-parsing calls and ai_generator.py's cover-letter-generation calls into the shared llm_client.py Ollama call helper, so two different multi-GB models could become resident at once with no serialization or explicit unload"
root_cause: thread_violation
resolution_type: code_fix
severity: high
related_components:
  - "pdf_parser.py (analyze_cv_text - CV parsing call site)"
  - "ai_generator.py (generate_application_content - cover-letter/application generation call site)"
tags: [ollama, concurrency, memory-pressure, docker, resource-management, keep-alive, threading-lock, llm-client]
---

# Two Ollama models (CV-parsing and application-generation) could be resident in memory simultaneously, risking Docker VM memory exhaustion

## Problem

`pdf_parser.analyze_cv_text()` (CV parsing, `qwen2.5:3b-instruct`) and `ai_generator.generate_application_content()` (cover-letter generation, `qwen2.5:7b-instruct`) both route through the shared `llm_client.generate_structured()` → `_call_chat()` helper, but nothing coordinated the two call sites or told Ollama to release a model promptly after use. FastAPI runs sync route handlers in a thread-pool, so a CV upload and a cover-letter generation request landing close together could genuinely have both models mid-generation — and therefore both resident in Ollama's memory — at the same time.

Found as a side-finding during a `ce-debug` investigation into a user report that the Profile page's "upload CV → analyze → auto-fill" flow was "not working and very slow." That investigation surfaced two other, separate, already-resolved root causes for that report (see **What Didn't Work** below) before this memory-residency risk turned up while live-reproducing the third.

## Symptoms

- `docker exec application-manager-ollama-1 ollama ps` showed both `qwen2.5:3b-instruct` (2.2GB) and `qwen2.5:7b-instruct` (5.1GB) loaded simultaneously during live reproduction.
- `docker stats` showed the Ollama container at 6.141GiB / 7.749GiB (79.24%) of Docker Desktop's total VM memory budget at that moment — confirmed via `docker info --format '{{.MemTotal}}'` and `docker inspect ... HostConfig.Memory` = `0` (unbounded per-container; the 7.749GiB is the whole VM's budget, shared with Postgres/backend/frontend).
- Once the 7b model's keep-alive expired (~5 minutes after its last use — Ollama's server-side default), memory dropped to 2.167GiB/7.749GiB (27.96%) with only the 3b model resident, confirming the two-models-loaded state was the abnormal, avoidable condition rather than steady-state usage.
- Net effect: CV upload in Profile became measurably slower and more failure-prone whenever it overlapped with a cover-letter generation request, on top of the already-slow CPU-only inference baseline.

## What Didn't Work

Not applicable in the usual "failed attempts" sense for this specific fix — it was reached directly via test-first implementation (write the two `TestModelResidency` tests, confirm they fail, implement the lock + `keep_alive=0`, confirm they pass) with no dead ends or discarded approaches.

What *is* worth recording is what this fix is **not** about, and where the underlying two-model setup actually came from:

1. **Missing Alembic migration** — a separate bug from the same `ce-debug` session, fixed as of this writing by commit `f71b3d8` on branch `develop` ("fix(backend): apply real Alembic migrations instead of create_all()") — not yet merged to `main`, so this SHA is local-only and may be rewritten by a future rebase/squash merge. Unrelated to Ollama memory; this doc is not about that fix.
2. **Inherent CPU-only Ollama inference latency** — already mitigated across two earlier sessions (see `backend/app/core/config.py:37-48` for the dedicated smaller `OLLAMA_MODEL_CV_PARSING` model introduced 2026-08-18, and `backend/app/core/config.py:49-65` for the `OLLAMA_TIMEOUT_SECONDS` history: 120.0 → 300.0 → 600.0, driven by live-measured ~2.2 tok/s CPU throughput). This fix does not touch model choice or timeout budgets — it only addresses concurrent residency, which compounds on top of that already-known slowness rather than being the same problem.
3. **The two-model split is itself the origin of this risk** (session history, 2026-08-18): the dedicated `OLLAMA_MODEL_CV_PARSING=qwen2.5:3b-instruct` model was introduced specifically because raising `OLLAMA_TIMEOUT_SECONDS` alone (120s → 300s) wasn't enough — a realistic CV still timed out at 300s on the 7b model. The 3b model was benchmarked directly (~3x faster, and, after correcting an initial test-prompt bug, just as accurate against the real production prompt) and scoped *only* to `pdf_parser.py`, deliberately leaving `ai_generator.py` on `OLLAMA_MODEL` (7b) — reasoned at the time as: swapping the model globally "would silently downgrade [cover-letter generation], an unrelated, currently-working feature too." That reasoning solved the latency/quality trade-off per call site correctly, but no session at the time considered what happens when *both* scoped models end up resident together — Ollama's `keep_alive` setting and model eviction/unloading behavior were never discussed in any of the five related prior sessions reviewed for this doc. The current fix closes that specific, previously-unexamined gap.
4. A same-day 2026-08-18 debug session (session history) also hit run-to-run variance during live testing — the same CV/prompt/model combination once timed out at 300s+ and once succeeded cleanly in 141s — attributed at the time to "CPU-load/timing variance on Docker Desktop." That variance is consistent with (though not proven to be caused by) the shared-Ollama-instance contention this fix addresses; it was never traced back to concurrent model residency at the time.

Conflating any of the above with this fix would be a mistake: this fix is specifically about preventing two different models from being generation-mid-flight (and therefore resident) at once, not about making any single inference call faster or changing which model handles which job.

## Solution

Fixed in commit `0516859` on branch `develop` ("fix(llm-client): stop the CV-parsing and application-generation models from being resident together"), file `backend/app/services/llm_client.py`. Not yet pushed or opened as a PR as of this writing.

Two changes:

**1. A module-level, process-wide lock** (`backend/app/services/llm_client.py:56`):

```python
_ollama_lock = threading.Lock()
```

**2. `_call_chat()`'s only `client.chat(...)` call site** now acquires that lock and passes `keep_alive=0` (`backend/app/services/llm_client.py:115-119`):

```python
try:
    with _ollama_lock:
        response = client.chat(
            model=model, format=format_schema, messages=messages, keep_alive=0
        )
except ollama.ResponseError as exc:
    ...
```

Before the fix, this was:

```python
response = client.chat(model=model, format=format_schema, messages=messages)
```

— no lock, no `keep_alive` override, so two threads could reach `client.chat()` concurrently with different `model=` values, and each model lingered resident for Ollama's default 5-minute keep-alive after its call finished.

Both call sites already went through this single helper, so the fix required no changes to the callers:
- `backend/app/services/pdf_parser.py:131-133` — `llm_client.generate_structured(ParsedCvProfile, messages, model=settings.OLLAMA_MODEL_CV_PARSING)`, i.e. `qwen2.5:3b-instruct` (`backend/app/core/config.py:48`).
- `backend/app/services/ai_generator.py:89` — `llm_client.generate_structured(AiGenerationResult, messages)`, which falls through to `resolved_model = model or settings.OLLAMA_MODEL` (`backend/app/services/llm_client.py:317`), i.e. `qwen2.5:7b-instruct` (`backend/app/core/config.py:36`).

A documented trade-off ships with the fix: a same-model retry/fallback within a single `generate_structured()` call (the existing retry-then-flatten-schema-fallback mechanism at `backend/app/services/llm_client.py:289-365`, for Ollama's `$defs`/`$ref` bug on nested list fields, `ollama/ollama#8444` — see **Related Issues** below) now reloads the model between its sequential `_call_chat()` calls instead of staying warm, since each call re-enters and releases the lock. This is called out as acceptable because that retry path is already the rare exception case, not the common path.

The lock is scoped per-`_call_chat()`, not per-`generate_structured()` — it is acquired and released around each individual `client.chat()` call, not held across a whole retry/fallback sequence. This means that sequence is not atomic with respect to other callers: a third concurrent request can acquire the lock in the gap between a request's first attempt and its retry, interleaving its own model load in the middle of that sequence. Under 3+ concurrent requests this can produce more reload churn than the simple two-actor case the regression test covers (`test_concurrent_calls_for_different_models_are_serialized` only exercises two single-shot calls, not an interleaved retry sequence).

## Why This Works

Ollama's server-side default is to keep a model resident for 5 minutes after its last use unless the caller overrides it. `ollama.Client.chat()` accepts a `keep_alive` kwarg per call; passing `keep_alive=0` (`backend/app/services/llm_client.py:118`) tells Ollama to unload the model immediately once that call completes, instead of leaving it resident to serve a hypothetical next call. That alone shrinks the *window* during which a model can be resident, but it doesn't prevent two *different* models from both being mid-generation (and therefore both resident) at once if two requests land close together — unloading only happens after a call finishes.

The lock closes that remaining gap. FastAPI serves sync route handlers from a thread pool, so the CV-parsing request handler and the cover-letter-generation request handler genuinely run on separate worker threads within the same backend process, both able to reach `_call_chat()` at effectively the same wall-clock moment. `_ollama_lock` (`backend/app/services/llm_client.py:56`, held across the `client.chat()` call at `backend/app/services/llm_client.py:116-119`) serializes access to the shared call site process-wide: whichever thread acquires it first must finish its `client.chat()` call — and, via `keep_alive=0`, trigger that model's unload — before the second thread's call for the other model can even start. The two conditions together (serialize access; unload promptly after each call) mean the two models are never simultaneously mid-generation, which was the state that produced the measured ~7.3GB combined residency against a 7.75GB VM budget.

Note: `_ollama_lock` serializes *all* `client.chat()` calls process-wide, not only cross-model ones — two concurrent requests for the *same* model (e.g., two simultaneous CV uploads) are also now fully serialized, where Ollama's own request queue could previously have served them in parallel (subject to `OLLAMA_NUM_PARALLEL`, unset/default here). Given this deployment's CPU-only, single-user, ~2.2 tok/s inference (see the `OLLAMA_TIMEOUT_SECONDS` history above), this is judged an acceptable trade-off rather than a meaningful throughput regression, but it has not been separately measured.

Classified `severity: high` above despite no confirmed crash: the 79.24% figure was measured against an *unbounded*, VM-wide budget shared with Postgres/backend/frontend (not a per-container limit — `HostConfig.Memory` was `0`), so exceeding it risks a whole-VM OOM rather than an isolated Ollama-container failure. The risk this fix closes is to the whole stack, not just AI inference.

## Prevention

- The `TestModelResidency` class in `backend/tests/services/test_llm_client.py:97-168` is the regression guard, added test-first (written and confirmed failing before implementation):
  - `test_chat_call_requests_immediate_unload_after_use` (`backend/tests/services/test_llm_client.py:112-117`) asserts `mock_client.chat.call_args.kwargs["keep_alive"] == 0`.
  - `test_concurrent_calls_for_different_models_are_serialized` (`backend/tests/services/test_llm_client.py:119-168`) drives two real threads through `generate_structured()` with different `model=` kwargs against a mocked client whose `chat()` blocks on a `threading.Event` for the first (`"model-a"`) call, and asserts via a shared `call_log` that the second thread's `client.chat()` cannot start until the first thread's call has fully completed (`assert call_log == ["start:model-a", "end:model-a", "start:model-b", "end:model-b"]`).
  - Full backend suite (112 tests) passes after the fix with no regressions, verified via `docker exec application-manager-backend-1 python -m pytest -q`.
- **Forward-looking rule**: any new code path that needs to talk to Ollama (or any other locally-hosted model server sharing this Docker Desktop VM's memory budget) must go through the existing shared helper — `llm_client.generate_structured()` (or, if a lower-level need arises, `_call_chat()` directly) — rather than constructing its own `ollama.Client()` and calling `.chat()` independently. A new call site that bypasses the helper bypasses `_ollama_lock` and `keep_alive=0` both, silently reintroducing the concurrent-residency window this fix closed. If a future change needs a genuinely different call pattern, extend `_call_chat()`/`generate_structured()` rather than adding a parallel call path.
- **When adding a third (or further) locally-hosted model to this backend**, re-check the combined worst-case resident footprint against the Docker Desktop VM's total memory budget (`docker info --format '{{.MemTotal}}'`) — the lock added here serializes *access*, but does not itself cap or reason about total memory; it only prevents the specific two-models-at-once state observed. A single very large model, or a future change to `keep_alive` values, could still approach the VM budget on its own.
- **To spot recurrence or drift**, periodically (or when memory pressure is suspected) run `docker exec application-manager-ollama-1 ollama ps` — it should never show more than one model resident at a time in normal operation — and/or `docker stats application-manager-ollama-1` against the known-bad baseline of ~79% VM memory from this investigation. If either shows two models loaded together again, `_ollama_lock`/`keep_alive=0` has likely been bypassed (see the "must go through the shared helper" rule above) or Ollama's `keep_alive` default has changed upstream.

## Related Issues

- `docs/solutions/integration-issues/ollama-structured-output-nested-list-schema-validation-failure.md` — same file and same two call sites (`llm_client.py` / `pdf_parser.py` / `ai_generator.py`), and the same test file (`test_llm_client.py`), but a different problem: that doc covers a schema-shape-driven Pydantic `ValidationError` in `generate_structured`/`_call_chat` (Ollama's `$defs`/`$ref` constrained-decoding bug, `ollama/ollama#8444`), fixed with retry + flattened-schema-fallback logic. This doc covers resource/memory coordination between the two call sites, fixed with locking + `keep_alive=0`. Worth reading together when working in `llm_client.py`, but neither supersedes the other.
- Commits `bc009ed` ("fix(cv-import): stop CV upload from timing out, silently, forever" — introduced the `OLLAMA_MODEL_CV_PARSING` split and the 120s→300s timeout raise) and `d6c9f57` ("profile cv fix") are prior, related fixes on the same CV-import reliability path, from the same investigation lineage that produced this fix's two-model setup — neither has its own `docs/solutions/` entry yet. As of this writing both SHAs are reachable from `origin/develop` (pushed), not yet merged to `main`, so cite them as historical pointers rather than stable identifiers (they may be rewritten by a future rebase/squash merge to `main`). A future `ce-compound-refresh` pass could backfill documentation for those if they come up again.
