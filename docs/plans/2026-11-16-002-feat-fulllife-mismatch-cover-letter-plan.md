---
title: Full-life Mismatch Cover Letter - Plan
type: feat
date: 2026-11-16
topic: fulllife-mismatch-cover-letter
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Full-life Mismatch Cover Letter - Plan

## Goal Capsule

- **Objective:** Make Full-life cover letters stay persuasive when the profile does not match the job ad, by detecting a field-level mismatch and replacing the terse gap note with one dedicated paragraph that names the mismatch honestly, brings in grounded transferable skills, and expresses interest plus a soft willingness to learn.
- **Product authority:** This plan, from brainstorm dialogue confirmed 2026-11-16.
- **Open blockers:** None.

---

## Product Contract

**Product Contract preservation:** Restructured, no scope change: R5 clarified to "role and, when the field differs, the new field" for the same-field core-gap case; AE8 added for that case; F1's framing step clarified; the deferred false-positive question is resolved by KTD6; the transferable-strengths assumption is made explicit by KTD3. R1-R4, R6-R10, KD1-KD4, F2, AE1-AE7 unchanged.

### Summary

Full-life cover letters gain an honest but positive career-change treatment. The existing fit assessment additionally judges whether the ad lies outside the profile's field. When that holds — or when a core requirement stays unmet — the letter writes one dedicated paragraph instead of the short gap note: it names the mismatch openly, cites a profile-grounded transferable skill, and expresses interest and a soft willingness to learn.

### Problem Frame

Cover-letter generation already runs a match analysis and grounds every claimed skill in profile evidence. Its honesty rule only fires on an unmet core requirement, though, and its response is a brief gap note. A Full-life application is often a field change rather than a single missing requirement: the ad sits in a different domain, or it matches every stated requirement while still being a different line of work. In that situation the current letter has no positive framing — it neither argues why the existing background transfers nor states a credible willingness to learn the field. The applicant is left with a letter that either overstates fit or says nothing useful about the mismatch.

### Requirements

**Mismatch detection**

- R1. The fit assessment additionally records an overall judgment of whether the job ad lies outside the profile's field, independent of any single requirement.
- R2. For a Full-life application, the mismatch case is triggered when either that field-mismatch judgment is positive or at least one core requirement is unmet.

**Mismatch paragraph**

- R3. In the mismatch case the Full-life letter contains exactly one dedicated, coherent paragraph that names the missing 1:1 fit openly; it replaces the existing short gap note for Full-life.
- R4. That paragraph names at least one concrete skill or experience from the profile that transfers to the target role, and briefly says why it helps; when the profile offers no grounded overlap, the paragraph invents none.
- R5. That paragraph expresses genuine interest in the role and, when the field differs, in the new field, plus a soft willingness to learn — readiness to familiarise themselves with the work and learn what is new.
- R6. The paragraph never claims an unmet core requirement is already met, and never claims an ongoing or completed retraining or further education unless the profile supports it.

**Continuity and scope**

- R7. When the mismatch case does not apply, the Full-life letter keeps its normal confident tone and contains no mismatch paragraph.
- R8. The IT profile keeps the existing short gap note; the new Full-life paragraph does not apply to IT.
- R9. On Regenerate, the mismatch verdict for the same profile/job pair stays stable; only wording and structure change between generations.
- R10. All existing letter rules continue to apply: no fabricated facts beyond the profile, the salutation fallback, the full name in the closing, German output, and the existing style rules.

### Key Decisions

- KD1. **Detect mismatch through the extended fit assessment — field mismatch or unmet core requirement — rather than a manual toggle or "always on Full-life".** (session-settled: user-directed — chosen over a manual trigger and over unconditional treatment: keeps the paragraph grounded in the actual ad.) Governs R1, R2.
- KD2. **Name the gap openly, then reframe it positively.** (session-settled: user-directed — chosen over not naming it explicitly and over letting the model decide: preserves credibility and forbids invented experience.) Governs R3, R4, R5, R6.
- KD3. **Use soft learning willingness instead of explicit retraining/further-education wording.** (session-settled: user-directed — chosen over explicit Umschulung/Weiterbildung wording: avoids promising a formal measure the profile does not support.) Governs R5, R6.
- KD4. **One dedicated Full-life paragraph replaces the short gap note.** (session-settled: user-directed — chosen over extending the note in place and over weaving it into the normal paragraphs: makes the reframing land as one coherent block.) Governs R3, R7, R8.

### Key Flows

- F1. Generate a Full-life letter in the mismatch case
  - **Trigger:** First-time generation or Regenerate for a Full-life application whose ad is outside the profile's field or leaves a core requirement unmet.
  - **Steps:** The fit assessment judges requirements plus overall field fit -> the mismatch case is derived per R2 -> the writing step replaces the short gap note with the dedicated paragraph -> the paragraph uses field-transfer framing when the field differs and role/skill framing when only a core gap remains -> the paragraph names the mismatch, cites a grounded transferable skill, and states interest plus soft learning willingness -> the remaining paragraphs keep their normal tone.
  - **Covers:** R1, R2, R3, R4, R5, R6.
- F2. Generate a Full-life letter without the mismatch case
  - **Trigger:** Full-life application with all core requirements met and no field mismatch.
  - **Steps:** The fit assessment finds no mismatch trigger -> the letter keeps its normal confident tone and includes no mismatch paragraph.
  - **Covers:** R7.

### Acceptance Examples

- AE1. **Covers R1, R2, R3, R4, R5.** Given a Full-life profile in a different field from the ad but with a concrete transferable experience, when the letter is generated, then it contains one paragraph that openly names the mismatch, cites that grounded experience and why it helps, and expresses interest plus soft willingness to learn — with no invented experience.
- AE2. **Covers R1, R2, R3.** Given a Full-life ad that matches every stated requirement but lies in a different field, when the letter is generated, then the dedicated paragraph appears and frames the case as transfer and interest, not as a missing requirement.
- AE3. **Covers R2, R7.** Given a Full-life application with no field mismatch, all core requirements met, and only a nice-to-have requirement missing, when the letter is generated, then it keeps its confident tone and contains no mismatch paragraph.
- AE4. **Covers R8.** Given an IT application with an unmet core requirement, when the letter is generated, then it keeps the existing short gap note and gains no Full-life mismatch paragraph.
- AE5. **Covers R4.** Given a Full-life field mismatch with no grounded transferable overlap in the profile, when the letter is generated, then the paragraph names the mismatch and the soft willingness to learn without inventing a transferable skill.
- AE6. **Covers R9.** Given an application whose stored letter reflects a mismatch case, when Regenerate runs for the same profile/job pair, then the new letter still treats it as a mismatch case; only wording and structure differ.
- AE7. **Covers R6.** Given a profile with no recorded retraining or further education, when the mismatch paragraph is written, then it never states that such a measure is underway or completed.
- AE8. **Covers R2, R3, R5.** Given a Full-life application in the correct field with one unmet core requirement and no field mismatch, when the letter is generated, then it contains one dedicated paragraph that names the missing core skill and expresses role/skill interest plus willingness to learn, without implying a field change.

### Scope Boundaries

- The IT letter behavior is unchanged and keeps the current short gap note (R8).
- The field-mismatch judgment is internal generation input; it is neither stored on the application nor shown in the UI.
- Already-generated or stored letters are not retroactively rechecked or rewritten; the change applies to new generations, including Regenerate.
- No explicit retraining or further-education offer is promised (see R5, R6).

### Dependencies / Assumptions

- Builds on the two-call generation pipeline and the honesty/Regenerate machinery from `docs/plans/2026-10-01-001-fix-cover-letter-fit-grounding-plan.md`; it changes what runs inside generation and does not change the API contract or the Regenerate UI.
- Assumes the local model can make the added overall field-mismatch judgment reliably enough alongside the existing per-requirement assessment.
- Assumes transferable strengths can be cited from the full profile content under an explicit transfer exception, not only from requirement matches.
- Assumes R9/AE6 are prompt-enforced best effort; the verdict is not persisted, so a model flip between generations is an accepted risk.

### Sources / Research

- `backend/app/services/ai_generator.py:30-151` — base and style system prompts, including `_STYLE_IT` / `_STYLE_FULL_LIFE` and the profile-type mapping.
- `backend/app/services/ai_generator.py:189-220` — `_build_user_prompt`; serializes only `requirements` today, so the derived trigger must be added here.
- `backend/app/services/ai_generator.py:228-366` — match-analysis prompt, writing prompt, and the sequential two-call pipeline.
- `backend/app/schemas/generation.py:18-59` — `RequirementAssessment` and `CoverLetterFitAssessment` shape and evidence validator.
- `backend/app/services/llm_client.py:199-262, 298-375` — structural-failure detection and the flattened-schema fallback; a new top-level scalar does not change the fallback path.
- `backend/app/api/applications.py:44-53, 145-266` — profile-content gate, job-offer loading, profile lock/selection, and generation persistence.
- `backend/app/core/config.py:78, 114` — current default model (`mistral-nemo:12b`) and the documented two-call timeout worst case; no timeout change is warranted.
- `backend/tests/services/test_ai_generator.py`, `backend/tests/services/test_ai_generator_profile_style.py`, `backend/tests/services/test_llm_client.py` — existing prompt-construction, style-branch, and schema tests.
- `docs/solutions/integration-issues/ollama-structured-output-nested-list-schema-validation-failure.md` — nested-list schema risk; motivates the scalar field and reusing existing evidence.
- `docs/solutions/performance-issues/ollama-concurrent-model-residency-memory-pressure.md` — why no third LLM call or new model is introduced.
- `docs/residual-review-findings/feat-cover-letter-generation-quality.md` — previous-letter block delimiting risk; this plan wraps that block in both prompt builders (KTD7).
- `docs/plans/2026-10-01-001-fix-cover-letter-fit-grounding-plan.md` — existing match-analysis, honest gap note, and Regenerate verdict-stability decisions this plan extends.
- `docs/plans/2026-09-23-001-feat-profile-types-plan.md` — IT vs Full-life style and manual profile selection.
- `CONCEPTS.md` — canonical "Mismatch case", "Profile language", and profile-domain vocabulary.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Add one top-level scalar `field_mismatch: bool` defaulting to `False` to the existing fit assessment; do not add a third LLM call and do not add a new nested list.** (session-settled: user-directed — inherits KD1's choice of the extended fit assessment over a manual trigger: the scalar keeps the two-call pipeline, avoids the repo's known Ollama `list[SubModel]` schema failure, and keeps IT/legacy and existing test fixtures valid.) Governs R1, R2.
- KTD2. **Keep the short gap note in the base system prompt and have the Full-life style block explicitly override it.** Moving the note out of the base would change IT and legacy behavior; the Full-life block states that its paragraph replaces the note, uses field-transfer framing only when the field differs, and uses role/skill framing for a same-field core gap. Governs R3, R5, R7, R8.
- KTD3. **Ground transferable claims in the full profile content through an explicit transfer exception, not a new structured strengths list.** A cross-field strength often has no requirement row, so the Full-life block may cite a real skill or experience from the profile even without a `matched` requirement, but never invent one. Add `berufsbezeichnung`, `projects`, and `languages` to the profile payload so this grounding is available. Governs R4, R6.
- KTD4. **Derive a single `mismatch_case` boolean in Python and serialize both `field_mismatch` and `mismatch_case` into the Full-life writing prompt.** Compute `mismatch_case = Full-life AND not degenerate AND (field_mismatch OR any unmet core requirement)`; pass the resolved profile type into `_build_user_prompt`. The writer needs `field_mismatch` to choose field-transfer versus role/skill framing, while IT receives neither key. This keeps IT's writing prompt unchanged, makes the field-mismatch-only case (AE2) explicit, and stops the base "no core gap means no note" rule from competing with the Full-life paragraph. Governs R2, R3, R7, R8.
- KTD5. **Extend Regenerate verdict stability to `field_mismatch` through the match-analysis prompt; do not persist the verdict.** This mirrors the existing per-requirement mechanism and the prior plan's KTD5. R9/AE6 remain prompt-enforced best effort; a model flip is an accepted risk. Governs R9.
- KTD6. **Use conservative defaults only for genuinely ambiguous input: no credible field signal means `field_mismatch=False`, while a broad or mixed profile is compared against the ad rather than treated as ambiguous.** Empty or whitespace-only descriptions, or ones shorter than a named module constant, set `mismatch_case=False` deterministically before writing. This avoids an unrequested career-change paragraph on degenerate ads without silently excluding adjacent-field career changers. Governs R1, R2, R7.
- KTD7. **Wrap the previous-letter block in the existing untrusted-data framing in both prompt builders.** KTD5 makes that stored, user-editable, ad-derived text an authority anchor for the field verdict, so it must be labeled as data rather than instructions. Update the tests that currently assert the block sits outside the delimiting. Governs R9.

### High-Level Technical Design

```mermaid
flowchart TB
  A[Profile + job ad] --> B[Match analysis: requirements + field_mismatch]
  B --> C{Description empty or below threshold?}
  C -->|yes| D[mismatch_case = false]
  C -->|no| E{match_case = Full-life AND (field_mismatch OR unmet core)}
  E --> F[mismatch_case]
  D --> F
  F --> G{Full-life AND mismatch_case?}
  G -->|yes| H[Writing: dedicated paragraph replaces the short note]
  G -->|no| I[Writing: normal tone; IT and legacy keep the short note]
  H --> J[cover_letter_text]
  I --> J
```

### Assumptions

- The local model can make the additional overall field judgment alongside the per-requirement assessment. No new model or call is added; the configured two-call timeout worst case stays unchanged.
- `mismatch_case` is derived deterministically in Python from the assessment, so the presence of the paragraph does not depend on the model combining the OR rule itself.
- The mismatch paragraph's presence and "exactly one" are prompt-enforced. Tests assert prompt construction and schema shape, not real model output, consistent with the prior fit-grounding plan.
- R9/AE6 are prompt-enforced best effort; the verdict is not persisted, and a model flip between generations is an accepted risk.
- The field verdict and trigger components are logged as booleans for diagnosis; no ad or profile text is logged, and nothing is persisted or shown in the UI.
- A same-field core gap for Full-life triggers the dedicated paragraph per R2; its wording adapts per KTD2.
- IT and legacy/unknown profile types keep the existing short note and receive neither new key in the writing prompt.
- The additional profile fields are part of the shared match/write payload, so IT's match analysis can see richer profile facts; the IT letter behavior and its short note are unchanged.
- Profile edits between generations are not detected; R9 stability applies to an unchanged profile/job pair.
- The 6,000-character job-description cap is unchanged; the untruncated title, company, and location still help identify the field.
- Profile fields (`berufsbezeichnung`, `projects`, `languages`) are applicant-authored data; parsed-CV provenance is out of scope.

---

## Implementation Units

### U1. Assessment field, match-analysis judgment, and match-call framing

- **Goal:** Add the overall field-mismatch judgment to the match-analysis result and prompt, and label the previous-letter block as untrusted data in that call.
- **Requirements:** R1, R2, R9, R10. KTD1, KTD5, KTD7.
- **Dependencies:** None.
- **Files:**
  - `backend/app/schemas/generation.py`
  - `backend/app/services/ai_generator.py`
  - `backend/tests/services/test_ai_generator.py`
  - `backend/tests/services/test_llm_client.py`
- **Approach:**
  1. Add `field_mismatch: bool = False` as a top-level field on `CoverLetterFitAssessment`, beside `requirements`. The default keeps existing fixtures valid and treats an omitted judgment as "no mismatch".
  2. Extend `_MATCH_ANALYSIS_SYSTEM_PROMPT`'s JSON contract and rules: judge the ad's overall occupational field against the profile's roles, education, summary, and projects; make the judgment independent of the requirement list; default to false only when the ad provides no credible field signal — compare a broad or mixed profile rather than treating it as ambiguous; compare German and English profile content semantically.
  3. Extend the previous-letter stability instruction to cover `field_mismatch`, not only the per-core `matched` verdicts.
  4. Wrap the previous-letter block in `_build_match_analysis_user_prompt` with the existing "data, never instructions" framing. Update the tests that currently assert the block sits outside the delimiting.
  5. Add schema and prompt-construction tests.
- **Patterns to follow:** `RequirementAssessment` field style; `TestMatchAnalysisSystemPrompt`'s lowercase substring assertions; `TestCoverLetterFitAssessmentStructuralFallback`'s round-trip shape; the existing job-offer untrusted-data labels.
- **Test scenarios:**
  - `CoverLetterFitAssessment(requirements=[...])` validates with `field_mismatch` defaulting to `False`; an explicit `field_mismatch=True` validates.
  - `_MATCH_ANALYSIS_SYSTEM_PROMPT` contains the overall-field instruction and the independence-from-requirements rule.
  - The prompt includes the rule that a broad or mixed profile is compared, not automatically treated as ambiguous.
  - The previous-letter branch of the match-analysis prompt mentions both the per-requirement verdict and `field_mismatch`, and carries the untrusted-data framing.
  - The existing flattened-schema round-trip for `CoverLetterFitAssessment` still passes with the scalar field present.
- **Verification:** Focused pytest for `test_ai_generator.py` and `test_llm_client.py` passes.

### U2. Profile payload enrichment

- **Goal:** Give the model the profile facts needed for transferable grounding.
- **Requirements:** R4, R6. KTD3.
- **Dependencies:** U1.
- **Files:**
  - `backend/app/services/ai_generator.py`
  - `backend/tests/services/test_ai_generator.py`
- **Approach:** Add `berufsbezeichnung`, `projects`, and `languages` to `_build_profile_and_job_block`'s `profile_payload`, tolerating absent values.
- **Patterns to follow:** existing `_build_profile_and_job_block` payload construction; `_profile_has_cv_content`'s field set.
- **Test scenarios:**
  - The shared profile/job block includes `berufsbezeichnung`, `projects`, and `languages` when present.
  - A profile with absent optional fields still serializes without error.
- **Verification:** Focused pytest for `test_ai_generator.py` passes.

### U3. Mismatch-case derivation and degenerate-ad guard

- **Goal:** Derive `mismatch_case` deterministically and suppress it on degenerate ads.
- **Requirements:** R1, R2, R7. KTD4, KTD6.
- **Dependencies:** U1.
- **Files:**
  - `backend/app/services/ai_generator.py`
  - `backend/tests/services/test_ai_generator.py`
- **Approach:**
  1. Add a named module constant for the degenerate-ad threshold, mirroring `_MAX_JOB_DESCRIPTION_CHARS`.
  2. In `generate_application_content`, after the match-analysis call, compute `mismatch_case = resolved_profile_type == "full_life" and description_length >= threshold and (field_mismatch or any core requirement unmet)`.
  3. Log `field_mismatch` and `mismatch_case` as booleans; log no ad or profile text.
  4. Pass `mismatch_case` to `_build_user_prompt` as the derived trigger.
  5. Add tests for every combination below.
- **Patterns to follow:** `_MAX_JOB_DESCRIPTION_CHARS` constant style; the existing `resolved_profile_type` resolution.
- **Test scenarios:**
  - Full-life, field mismatch, all requirements matched -> `mismatch_case=True`.
  - Full-life, same field, one core gap -> `mismatch_case=True`.
  - Full-life, same field, all core matched, nice-to-have missing -> `mismatch_case=False`.
  - Full-life, empty or whitespace-only description -> `mismatch_case=False`.
  - Full-life, description shorter than the threshold -> `mismatch_case=False`.
  - IT with a field mismatch or core gap -> `mismatch_case=False`.
  - Normal-length description, no mismatch, no core gap -> `mismatch_case=False`.
- **Verification:** Focused pytest for `test_ai_generator.py` passes.

### U4. Writing-prompt restructure and write-call framing

- **Goal:** Render the dedicated Full-life paragraph from `mismatch_case`, keep IT and legacy unchanged, and preserve the existing letter rules.
- **Requirements:** R3, R4, R5, R6, R7, R8, R9, R10. KTD2, KTD3, KTD4, KTD7.
- **Dependencies:** U1, U2, U3.
- **Files:**
  - `backend/app/services/ai_generator.py`
  - `backend/tests/services/test_ai_generator.py`
  - `backend/tests/services/test_ai_generator_profile_style.py`
- **Approach:**
  1. `_build_user_prompt` accepts `mismatch_case: bool | None = None`; when it is not `None`, include both `field_mismatch` and `mismatch_case` in the assessment block. The caller passes it only for Full-life, so IT and legacy receive neither key.
  2. Add a Full-life block to `_STYLE_FULL_LIFE` keyed on `mismatch_case`. It requires exactly one paragraph, open naming of the mismatch, field-transfer framing when the field differs, role/skill framing for a same-field core gap, a grounded transferable skill or the no-overlap fallback, soft learning willingness rather than explicit Umschulung/Weiterbildung wording (per R5, R6, KD3), and no claim that an unmet core requirement is met (per R6).
  3. State explicitly that when `mismatch_case` is true the dedicated paragraph is required even if no requirement is unmatched (the field-mismatch-only case), and that the base "no core gap means no note" rule does not apply. This overrides the base note rather than competing with it.
  4. State that the paragraph counts within the existing 3-5 paragraphs and that its presence and role stay invariant on Regenerate.
  5. Wrap the previous-letter block in `_build_user_prompt` with the same untrusted-data framing. Update the test that currently asserts the block sits outside the delimiting.
  6. Add a continuity test that the existing base and style rules still hold, so R10 cannot drift silently.
- **Patterns to follow:** additive `_STYLE_IT` / `_STYLE_FULL_LIFE` blocks; `TestBuildSystemPromptStyleBranches`' leakage-guard style; `TestBuildUserPrompt`'s assessment-block assertions.
- **Test scenarios:**
  - `_build_user_prompt` with `mismatch_case=True` includes both `field_mismatch` and `mismatch_case` in the assessment block; with `mismatch_case=None` it includes neither.
  - `_build_system_prompt("full_life")` contains the dedicated-paragraph instruction, the open-naming rule, the no-overlap rule, the forbidden "Umschulung"/"Weiterbildung" wording, the exactly-one-paragraph rule, and the Regenerate invariance rule.
  - `_build_system_prompt("full_life")` states that the paragraph is required when `mismatch_case` is true even with no unmatched core requirement (AE2 override).
  - `_build_system_prompt("it")` contains the existing short note and no Full-life override text.
  - `_build_system_prompt(None)` returns the base prompt with the short note.
  - The assessment-block and previous-letter untrusted-data labels are present.
  - The existing base-prompt rules (salutation fallback, full name, German output, no fabricated facts) are still asserted to be present after the prompt edits.
- **Verification:** Focused pytest for both prompt-construction files passes.

---

## Verification Contract

| Scope | Command | Applies to |
|---|---|---|
| Focused backend tests | `cd backend && venv/bin/pytest tests/services/test_ai_generator.py tests/services/test_ai_generator_profile_style.py tests/services/test_llm_client.py` | U1, U2, U3, U4 |
| Full backend suite | `cd backend && venv/bin/pytest` | U1, U2, U3, U4 |

No frontend application-code change, no API contract change, and no `nginx.conf` or timeout change. Manual real-model probes below cover what prompt-construction tests cannot assert.

---

## Definition of Done

- U1, U2, U3, and U4 are implemented.
- Focused and full backend test commands pass.
- Prompt-construction tests cover IT note retention, the Full-life override, the field-mismatch-only override (AE2), the no-overlap fallback, the forbidden retraining wording, `mismatch_case` serialization, Regenerate invariance, and the R10 continuity rules.
- Schema tests cover the `field_mismatch` default, the explicit true case, and the existing flatten-fallback round-trip.
- The mismatch-case derivation and degenerate-ad guard tests pass for every listed combination.
- The previous-letter block carries untrusted-data framing in both prompt builders, and the old "outside the delimiting" assertions are updated.
- Manual real-model probes, performed by the implementer against the local model:
  - Field mismatch with all requirements matched (AE2) produces the dedicated paragraph.
  - Same field, all core matched, nice-to-have missing (AE3) keeps the confident tone and no mismatch paragraph.
  - Same field with one core gap (AE8) produces role/skill framing and no false career-change narrative.
  - Field mismatch with no grounded overlap (AE5) invents no transferable skill.
  - An English profile against a German ad yields the correct field judgment and a German letter.
  - Two consecutive Regenerate runs keep the mismatch paragraph's presence and verdict stable (AE6, best effort).
  - An IT application with a core gap keeps the short gap note only (AE4).
- No dead code from discarded approaches remains in the diff.
- The Product Contract preservation note accurately records the R5 clarification and the AE8 addition.
