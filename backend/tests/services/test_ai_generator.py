"""Tests für `app.services.ai_generator` (siehe U4 des Plans:
docs/plans/2026-08-17-001-refactor-openai-to-ollama-migration-plan.md).
"""
from __future__ import annotations

import pytest

from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.schemas.generation import AiGenerationResult
from app.services import ai_generator
from app.services.ai_generator import ApplicationGenerationError, _build_user_prompt
from app.services.llm_client import LlmUnavailableError, LlmValidationError


def _profile(**overrides) -> MasterProfile:
    defaults = dict(
        full_name="Max Mustermann",
        email="max@example.com",
        phone="0123-456789",
        address="Musterstraße 1, 12345 Musterstadt",
        summary="Erfahrener Softwareentwickler.",
        experiences_json=[
            {
                "company": "Acme GmbH",
                "role": "Backend-Entwickler",
                "start_date": "2020",
                "end_date": None,
                "description": "Backend-Entwicklung mit Python.",
            }
        ],
        education_json=[
            {
                "institution": "TU Musterstadt",
                "degree": "B.Sc. Informatik",
                "field_of_study": "Informatik",
                "start_date": "2016",
                "end_date": "2020",
            }
        ],
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


VALID_RESULT = AiGenerationResult(
    cover_letter_text="Betreff: Bewerbung als Senior Backend-Entwickler\n\nSehr geehrte Damen und Herren,\n\n...\n\nMit freundlichen Grüßen\nMax Mustermann",
)


class TestGenerateApplicationContentHappyPath:
    def test_returns_cover_letter_text_from_helper(self, mocker):
        mock_generate = mocker.patch.object(
            ai_generator.llm_client, "generate_structured", return_value=VALID_RESULT
        )

        profile = _profile()
        job_offer = _job_offer()

        cover_letter_text = ai_generator.generate_application_content(profile, job_offer)

        assert cover_letter_text == VALID_RESULT.cover_letter_text

        mock_generate.assert_called_once()
        called_model_cls, called_messages = mock_generate.call_args[0]
        assert called_model_cls is AiGenerationResult
        assert called_messages[0] == {"role": "system", "content": ai_generator._SYSTEM_PROMPT}
        assert called_messages[1] == {
            "role": "user",
            "content": _build_user_prompt(profile, job_offer),
        }


class TestGenerateApplicationContentValidationFailure:
    def test_llm_validation_error_becomes_application_generation_error(self, mocker):
        mocker.patch.object(
            ai_generator.llm_client,
            "generate_structured",
            side_effect=LlmValidationError("schema mismatch"),
        )

        with pytest.raises(ApplicationGenerationError):
            ai_generator.generate_application_content(_profile(), _job_offer())


class TestGenerateApplicationContentUnavailable:
    def test_llm_unavailable_error_becomes_application_generation_error(self, mocker):
        mocker.patch.object(
            ai_generator.llm_client,
            "generate_structured",
            side_effect=LlmUnavailableError("Ollama ist nicht erreichbar"),
        )

        with pytest.raises(ApplicationGenerationError):
            ai_generator.generate_application_content(_profile(), _job_offer())


class TestBuildUserPrompt:
    def test_includes_profile_and_job_data(self):
        profile = _profile()
        job_offer = _job_offer()

        prompt = _build_user_prompt(profile, job_offer)

        assert profile.full_name in prompt
        assert job_offer.title in prompt
        assert job_offer.company in prompt
        assert job_offer.location in prompt
        assert job_offer.description_text in prompt

    def test_truncates_job_description_at_max_chars(self):
        long_description = "x" * (ai_generator._MAX_JOB_DESCRIPTION_CHARS + 500)
        job_offer = _job_offer(description_text=long_description)

        prompt = _build_user_prompt(_profile(), job_offer)

        assert long_description not in prompt
        assert "x" * ai_generator._MAX_JOB_DESCRIPTION_CHARS in prompt
        # Genau am Limit abgeschnitten, kein Zeichen mehr.
        assert "x" * (ai_generator._MAX_JOB_DESCRIPTION_CHARS + 1) not in prompt

    def test_missing_description_becomes_empty_string(self):
        job_offer = _job_offer(description_text=None)

        prompt = _build_user_prompt(_profile(), job_offer)

        assert '"description": ""' in prompt
