"""Tests für U4 (profil-typ-abhängiger Generierungsstil, R6/R7):
docs/plans/2026-09-19-001-feat-cover-letter-generation-quality-plan.md.

Reine Prompt-Konstruktions-Tests - keine LLM-Aufrufe (weder echt noch
gemockt); es wird nur der konstruierte System-Prompt-String inspiziert.
"""
from __future__ import annotations

from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.services import ai_generator


def _profile(**overrides) -> MasterProfile:
    defaults = dict(
        full_name="Max Mustermann",
        email="max@example.com",
        phone="0123-456789",
        address="Musterstraße 1, 12345 Musterstadt",
        summary="Erfahrener Softwareentwickler.",
        experiences_json=[],
        education_json=[],
        skills_json=["Python", "SQL"],
    )
    defaults.update(overrides)
    return MasterProfile(**defaults)


def _job_offer(**overrides) -> JobOffer:
    defaults = dict(
        title="Senior Backend-Entwickler",
        company="Beta AG",
        location="Berlin",
        source_url="https://example.com/jobs/1",
        description_text="Wir suchen einen erfahrenen Backend-Entwickler.",
        source_platform="test",
    )
    defaults.update(overrides)
    return JobOffer(**defaults)


class TestBuildSystemPromptStyleBranches:
    def test_it_and_full_life_produce_genuinely_different_style_text(self):
        it_prompt = ai_generator._build_system_prompt("it")
        full_life_prompt = ai_generator._build_system_prompt("full_life")

        assert it_prompt != full_life_prompt

        it_lower = it_prompt.lower()
        full_life_lower = full_life_prompt.lower()

        # IT style: concise/technical/skills-and-tech-stack-forward.
        assert "knapp" in it_lower or "präzis" in it_lower
        assert "tech-stack" in it_lower or "skills" in it_lower or "technolog" in it_lower

        # Full-life style: broader/narrative/comprehensive.
        assert "erzählerisch" in full_life_lower
        assert "geschichte" in full_life_lower or "roten faden" in full_life_lower

        # Each style block must not leak into the other's prompt.
        assert "erzählerisch" not in it_lower
        assert "tech-stack" not in full_life_lower

    def test_both_style_prompts_still_contain_unchanged_base_constraints(self):
        """R7 is an addition, not a replacement - core rules (no fabricated
        facts, salutation fallback, full name in closing) must survive."""
        for profile_type in ("it", "full_life"):
            prompt = ai_generator._build_system_prompt(profile_type)
            assert "Erfinde KEINE Fakten" in prompt
            assert "Sehr geehrte Damen und Herren" in prompt
            assert "vollständige Name aus dem Bewerberprofil" in prompt

    def test_none_or_unknown_profile_type_falls_back_to_base_prompt_unchanged(self):
        assert ai_generator._build_system_prompt(None) == ai_generator._SYSTEM_PROMPT
        assert ai_generator._build_system_prompt("unknown") == ai_generator._SYSTEM_PROMPT


class TestGenerateApplicationContentThreadsProfileType:
    def test_profile_type_argument_selects_the_matching_style_block(self, mocker):
        mock_generate = mocker.patch.object(
            ai_generator.llm_client,
            "generate_structured",
            return_value=ai_generator.AiGenerationResult(
                cover_letter_text="Betreff: ...\n\nSehr geehrte Damen und Herren,\n\n...\n\nMit freundlichen Grüßen\nMax Mustermann"
            ),
        )

        ai_generator.generate_application_content(
            _profile(), _job_offer(), profile_type="it"
        )

        called_messages = mock_generate.call_args[0][1]
        system_content = called_messages[0]["content"]
        assert system_content == ai_generator._build_system_prompt("it")
        assert "tech-stack" in system_content.lower() or "skills" in system_content.lower()

    def test_profile_type_not_silently_ignored_when_omitted_but_set_on_profile(self, mocker):
        """When the explicit `profile_type` kwarg is omitted, the function
        falls back to `profile.profile_type` (always correctly resolved per
        U3) rather than dropping style selection entirely."""
        mock_generate = mocker.patch.object(
            ai_generator.llm_client,
            "generate_structured",
            return_value=ai_generator.AiGenerationResult(
                cover_letter_text="Betreff: ...\n\nSehr geehrte Damen und Herren,\n\n...\n\nMit freundlichen Grüßen\nMax Mustermann"
            ),
        )

        profile = _profile(profile_type="full_life")
        ai_generator.generate_application_content(profile, _job_offer())

        called_messages = mock_generate.call_args[0][1]
        system_content = called_messages[0]["content"]
        assert system_content == ai_generator._build_system_prompt("full_life")
        assert "erzählerisch" in system_content.lower()

    def test_default_behaviour_unchanged_when_profile_has_no_profile_type(self, mocker):
        """Regression: a profile without a profile_type (nullable per U1)
        still gets exactly the base system prompt, no style block."""
        mock_generate = mocker.patch.object(
            ai_generator.llm_client,
            "generate_structured",
            return_value=ai_generator.AiGenerationResult(
                cover_letter_text="Betreff: ...\n\nSehr geehrte Damen und Herren,\n\n...\n\nMit freundlichen Grüßen\nMax Mustermann"
            ),
        )

        ai_generator.generate_application_content(_profile(), _job_offer())

        called_messages = mock_generate.call_args[0][1]
        assert called_messages[0]["content"] == ai_generator._SYSTEM_PROMPT
