"""Tests für `app.services.portal_agents.answering` (U5 des Plans:
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md).

Spiegelt die Mock-Konventionen aus `tests/services/test_ai_generator.py`
(`mocker.patch.object(<modul>.llm_client, "generate_structured", ...)`).
"""
from __future__ import annotations

import pytest

from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.schemas.portal_fill import PortalAnswerResult
from app.services.portal_agents import answering
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


VALID_RESULT = PortalAnswerResult(
    answer="Ich bringe mehrjährige Erfahrung in der Backend-Entwicklung mit Python mit."
)

QUESTION = "Warum möchten Sie bei uns arbeiten?"


class TestAnswerFreetextQuestionHappyPath:
    def test_returns_answer_from_helper_and_prompt_contains_all_context(self, mocker):
        mock_generate = mocker.patch.object(
            answering.llm_client, "generate_structured", return_value=VALID_RESULT
        )
        profile = _profile()
        job_offer = _job_offer()
        cover_letter_text = "Betreff: Bewerbung als Senior Backend-Entwickler\n\n..."

        answer = answering.answer_freetext_question(
            QUESTION, profile, job_offer, cover_letter_text
        )

        assert answer is VALID_RESULT

        mock_generate.assert_called_once()
        called_model_cls, called_messages = mock_generate.call_args[0]
        assert called_model_cls is PortalAnswerResult
        assert called_messages[0]["role"] == "system"
        user_content = called_messages[1]["content"]
        assert QUESTION in user_content
        assert profile.full_name in user_content
        assert job_offer.description_text in user_content
        assert cover_letter_text in user_content


class TestAnswerFreetextQuestionNoCoverLetterYet:
    def test_none_cover_letter_text_still_produces_answer(self, mocker):
        mock_generate = mocker.patch.object(
            answering.llm_client, "generate_structured", return_value=VALID_RESULT
        )
        profile = _profile()
        job_offer = _job_offer()

        answer = answering.answer_freetext_question(QUESTION, profile, job_offer, None)

        assert answer is VALID_RESULT
        user_content = mock_generate.call_args[0][1][1]["content"]
        assert QUESTION in user_content
        assert profile.full_name in user_content
        assert job_offer.description_text in user_content


class TestAnswerFreetextQuestionErrorPropagation:
    def test_llm_validation_error_propagates_unmodified(self, mocker):
        original = LlmValidationError("schema mismatch")
        mocker.patch.object(
            answering.llm_client, "generate_structured", side_effect=original
        )

        with pytest.raises(LlmValidationError) as exc_info:
            answering.answer_freetext_question(QUESTION, _profile(), _job_offer(), None)

        assert exc_info.value is original

    def test_llm_unavailable_error_propagates_unmodified(self, mocker):
        original = LlmUnavailableError("Ollama ist nicht erreichbar")
        mocker.patch.object(
            answering.llm_client, "generate_structured", side_effect=original
        )

        with pytest.raises(LlmUnavailableError) as exc_info:
            answering.answer_freetext_question(QUESTION, _profile(), _job_offer(), None)

        assert exc_info.value is original


class TestAnsweringDoesNotBuildItsOwnLlmClient:
    def test_module_has_no_direct_ollama_import(self):
        import inspect

        source = inspect.getsource(answering)
        assert "import ollama" not in source
        assert "ollama.Client" not in source
        assert "generate_structured" in source


class TestIsScreeningQuestion:
    """R12/KTD6: Screening-Familien werden deny-by-default erkannt."""

    @pytest.mark.parametrize(
        "question",
        [
            "Besitzen Sie eine gültige Arbeitserlaubnis?",
            "Sind Sie berechtigt, in Deutschland zu arbeiten?",
            "Welche Staatsangehörigkeit haben Sie?",
            "Benötigen Sie ein Visum oder Sponsoring?",
            "Haben Sie Vorstrafen?",
            "Do you require visa sponsorship?",
            "Are you authorized to work in the EU?",
            "Please provide a criminal record check.",
        ],
    )
    def test_matches_screening_families(self, question):
        assert answering.is_screening_question(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "Warum möchten Sie bei uns arbeiten?",
            "Was sind Ihre Gehaltsvorstellungen?",
            "Wann können Sie anfangen?",
        ],
    )
    def test_non_screening_question_is_not_flagged(self, question):
        assert answering.is_screening_question(question) is False

    def test_case_and_umlaut_variants_match(self):
        assert answering.is_screening_question("ARBEITSERLAUBNIS") is True
        assert answering.is_screening_question("Staatsangehörigkeit") is True
        assert answering.is_screening_question("Führungszeugnis") is True

    def test_none_or_empty_is_not_screening(self):
        assert answering.is_screening_question(None) is False
        assert answering.is_screening_question("") is False


class TestPortalAnswerResultSchema:
    def test_insufficient_information_defaults_to_false(self):
        assert PortalAnswerResult(answer="Antwort").insufficient_information is False

    def test_insufficient_information_can_be_set(self):
        result = PortalAnswerResult(answer="", insufficient_information=True)
        assert result.insufficient_information is True
