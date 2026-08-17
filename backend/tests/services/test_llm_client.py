"""Tests für den gemeinsamen Ollama-Aufruf-Helfer (siehe U7 des Plans:
docs/plans/2026-08-17-001-refactor-openai-to-ollama-migration-plan.md).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.generation import AiGenerationResult
from app.schemas.master_profile import ParsedCvProfile
from app.services import llm_client


def _response(payload: dict) -> SimpleNamespace:
    """Baut ein Fake-`ChatResponse`-Objekt mit `.message.content`."""
    return SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))


def _messages() -> list[dict]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


VALID_PROFILE = {
    "full_name": "Max Mustermann",
    "email": "max@example.com",
    "phone": None,
    "address": None,
    "summary": "Erfahrener Entwickler.",
    "experiences": [
        {
            "company": "Acme GmbH",
            "role": "Entwickler",
            "start_date": "2020",
            "end_date": None,
            "description": "Backend-Entwicklung.",
        }
    ],
    "education": [],
    "skills": ["Python"],
}


@pytest.fixture
def mock_client(mocker):
    """Patcht `ollama.Client` im Helfer-Modul und liefert das Client-Mock."""
    client_instance = mocker.MagicMock()
    mocker.patch.object(llm_client.ollama, "Client", return_value=client_instance)
    return client_instance


class TestHappyPath:
    def test_first_attempt_success_returns_validated_content(self, mock_client):
        mock_client.chat.return_value = _response(VALID_PROFILE)

        result = llm_client.generate_structured(ParsedCvProfile, _messages())

        assert isinstance(result, ParsedCvProfile)
        assert result.full_name == "Max Mustermann"
        assert result.experiences[0].company == "Acme GmbH"
        assert mock_client.chat.call_count == 1


class TestRetrySuccess:
    def test_retry_includes_validation_error_and_succeeds(self, mock_client):
        # Erste Antwort verletzt das Schema: "experiences[0].company" fehlt.
        invalid_payload = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [{"role": "Entwickler"}],
            "education": [],
            "skills": [],
        }
        invalid_content = json.dumps(invalid_payload)
        try:
            ParsedCvProfile.model_validate_json(invalid_content)
            raise AssertionError("Erwartete ValidationError für invalid_payload")
        except ValidationError as exc:
            expected_error_text = str(exc)

        mock_client.chat.side_effect = [
            _response(invalid_payload),
            _response(VALID_PROFILE),
        ]

        result = llm_client.generate_structured(ParsedCvProfile, _messages())

        assert isinstance(result, ParsedCvProfile)
        assert result.full_name == "Max Mustermann"
        assert mock_client.chat.call_count == 2

        retry_call = mock_client.chat.call_args_list[1]
        retry_messages = retry_call.kwargs["messages"]
        combined_retry_text = " ".join(m["content"] for m in retry_messages)
        assert expected_error_text in combined_retry_text
        assert invalid_content in combined_retry_text


class TestRetryExhaustedNonStructural:
    def test_two_different_non_list_failures_raise_validation_error(self, mock_client):
        # Erster Fehler: full_name hat falschen Typ (Top-Level-Feld).
        first_invalid = {
            "full_name": 12345,
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [],
            "education": [],
            "skills": [],
        }
        # Zweiter Fehler: email ungültig formatiert - anderes Feld, kein
        # verschachteltes Listenfeld -> kein strukturelles Signal.
        second_invalid = {
            "full_name": "Max Mustermann",
            "email": "not-an-email",
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [],
            "education": [],
            "skills": [],
        }

        mock_client.chat.side_effect = [
            _response(first_invalid),
            _response(second_invalid),
        ]

        with pytest.raises(llm_client.LlmValidationError):
            llm_client.generate_structured(ParsedCvProfile, _messages())

        # Kein dritter (Fallback-)Aufruf, da nicht strukturell.
        assert mock_client.chat.call_count == 2


class TestStructuralFailureFallback:
    def test_same_nested_list_field_triggers_flattened_fallback(self, mock_client):
        # Erster Fehler: experiences[0] fehlt "company".
        first_invalid = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [{"role": "Entwickler"}],
            "education": [],
            "skills": [],
        }
        # Zweiter Fehler: experiences[1] fehlt "role" - anderer Index/Feld,
        # aber dasselbe verschachtelte Listenfeld "experiences" -> strukturell.
        second_invalid = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [
                {"company": "Acme GmbH", "role": "Entwickler"},
                {"company": "Beta AG"},
            ],
            "education": [],
            "skills": [],
        }
        # Fallback-Antwort: abgeflachtes Schema, Listenfelder als JSON-Strings.
        flat_payload = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": "Zusammenfassung.",
            "experiences": json.dumps(
                [
                    {
                        "company": "Acme GmbH",
                        "role": "Entwickler",
                        "start_date": "2020",
                        "end_date": None,
                        "description": None,
                    }
                ]
            ),
            "education": json.dumps([]),
            "skills": ["Python"],
        }

        mock_client.chat.side_effect = [
            _response(first_invalid),
            _response(second_invalid),
            _response(flat_payload),
        ]

        result = llm_client.generate_structured(ParsedCvProfile, _messages())

        assert isinstance(result, ParsedCvProfile)
        assert result.full_name == "Max Mustermann"
        assert len(result.experiences) == 1
        assert result.experiences[0].company == "Acme GmbH"
        assert result.education == []
        assert result.skills == ["Python"]
        assert mock_client.chat.call_count == 3

        # Der dritte Aufruf muss gegen ein anderes (abgeflachtes) Schema
        # laufen als die ersten beiden.
        first_format = mock_client.chat.call_args_list[0].kwargs["format"]
        fallback_format = mock_client.chat.call_args_list[2].kwargs["format"]
        assert first_format != fallback_format

    def test_nested_submodel_list_field_also_detected_as_structural(self, mock_client):
        """Verschachtelung eine Ebene tiefer (AiGenerationResult.cv_content.experiences)."""
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
        flat_payload = {
            "cover_letter_text": "Anschreiben",
            "cv_content": {
                "summary": "S",
                "experiences": json.dumps(
                    [
                        {
                            "company": "Acme GmbH",
                            "role": "Entwickler",
                            "start_date": None,
                            "end_date": None,
                            "description": None,
                        }
                    ]
                ),
                "education": json.dumps([]),
                "skills": [],
            },
        }

        mock_client.chat.side_effect = [
            _response(first_invalid),
            _response(second_invalid),
            _response(flat_payload),
        ]

        result = llm_client.generate_structured(AiGenerationResult, _messages())

        assert isinstance(result, AiGenerationResult)
        assert result.cv_content.experiences[0].company == "Acme GmbH"
        assert mock_client.chat.call_count == 3


class TestUnavailable:
    def test_connection_error_raises_unavailable(self, mock_client):
        mock_client.chat.side_effect = ConnectionError("connection refused")

        with pytest.raises(llm_client.LlmUnavailableError):
            llm_client.generate_structured(ParsedCvProfile, _messages())

        # Keine Retries bei Nichterreichbarkeit.
        assert mock_client.chat.call_count == 1

    def test_timeout_raises_unavailable_distinct_from_connection_error(self, mock_client):
        mock_client.chat.side_effect = httpx.TimeoutException("timed out")

        with pytest.raises(llm_client.LlmUnavailableError):
            llm_client.generate_structured(ParsedCvProfile, _messages())

        assert mock_client.chat.call_count == 1
        # Sicherstellen, dass hier tatsächlich der httpx.TimeoutException-Pfad
        # griff, nicht zufällig derselbe wie beim ConnectionError-Test: die
        # Exception-Klassen sind unabhängige Hierarchien (httpx.TimeoutException
        # ist kein ConnectionError und umgekehrt).
        assert not isinstance(httpx.TimeoutException("x"), ConnectionError)
        assert not isinstance(ConnectionError("x"), httpx.TimeoutException)


class TestResponseError:
    def test_ollama_response_error_raises_unavailable(self, mock_client):
        import ollama

        mock_client.chat.side_effect = ollama.ResponseError("model not found", 404)

        with pytest.raises(llm_client.LlmUnavailableError):
            llm_client.generate_structured(ParsedCvProfile, _messages())

        assert mock_client.chat.call_count == 1
