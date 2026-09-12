"""Tests für den gemeinsamen Ollama-Aufruf-Helfer (siehe U7 des Plans:
docs/plans/2026-08-17-001-refactor-openai-to-ollama-migration-plan.md).
"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.master_profile import EducationEntry, ExperienceEntry, ParsedCvProfile
from app.services import llm_client


class _NestedSubmodelContent(BaseModel):
    """Test-lokales Modell mit einem verschachtelten Listenfeld, rein um den
    generischen Abflach-Fallback des Helfers gegen ein Submodell (statt
    gegen das Top-Level-Modell) zu prüfen - unabhängig von echten
    App-Schemas, die inzwischen flach sind (siehe `AiGenerationResult`)."""

    summary: str
    experiences: list[ExperienceEntry]
    education: list[EducationEntry]
    skills: list[str]


class _NestedSubmodelResult(BaseModel):
    cover_letter_text: str
    cv_content: _NestedSubmodelContent


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
    "skills": [{"name": "Python", "category": "Backend"}],
}


@pytest.fixture
def mock_client(mocker):
    """Patcht `ollama.Client` im Helfer-Modul und liefert das Client-Mock.

    `generate_structured` benutzt den Client als Context-Manager
    (`with _build_client() as client:`), daher muss `__enter__` explizit
    das Mock selbst zurückgeben (sonst liefert die Standard-MagicMock-
    Auto-Spezifizierung ein unkonfiguriertes Kind-Mock) und `__exit__` einen
    falsy Wert (sonst würde eine im Block ausgelöste Exception verschluckt).
    """
    client_instance = mocker.MagicMock()
    client_instance.__enter__.return_value = client_instance
    client_instance.__exit__.return_value = False
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


class TestModelResidency:
    """Regression guard for concurrent Ollama model residency (see ce-debug-
    Untersuchung, 2026-08-20: CV-Import 'nicht funktionierend/sehr langsam').

    Live-reproduced during that investigation: the CV-parsing model
    (qwen2.5:3b-instruct) and the application-generation model
    (qwen2.5:7b-instruct) can end up loaded into Ollama at the same time
    (Ollama's default 5-minute keep-alive keeps a model resident well after
    its call finished), and together they measured ~7.3GB against a
    Docker Desktop VM with only 7.75GB total - shared with Postgres/backend/
    frontend too. Two changes close this: `keep_alive=0` so a model doesn't
    linger after its call, and a process-wide lock so two different models
    can never be mid-generation (and therefore resident) at the same
    moment."""

    def test_chat_call_requests_immediate_unload_after_use(self, mock_client):
        mock_client.chat.return_value = _response(VALID_PROFILE)

        llm_client.generate_structured(ParsedCvProfile, _messages())

        assert mock_client.chat.call_args.kwargs["keep_alive"] == 0

    def test_concurrent_calls_for_different_models_are_serialized(self, mocker):
        """Two `generate_structured` calls for two different models (the
        CV-parsing and application-generation use cases) must never have
        their `client.chat()` calls in flight at the same time - that's the
        window in which both models would be resident together."""
        call_log: list[str] = []
        first_call_started = threading.Event()
        release_first_call = threading.Event()

        def fake_chat(*, model: str, **_kwargs: Any) -> SimpleNamespace:
            call_log.append(f"start:{model}")
            if model == "model-a":
                first_call_started.set()
                # Hält den Lock absichtlich, bis der zweite Aufruf (anderes
                # Modell) nachweislich noch NICHT gestartet ist.
                assert release_first_call.wait(timeout=2), "Test-Deadlock"
            call_log.append(f"end:{model}")
            return _response(VALID_PROFILE)

        client_instance = mocker.MagicMock()
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = False
        client_instance.chat.side_effect = fake_chat
        mocker.patch.object(llm_client.ollama, "Client", return_value=client_instance)

        thread_a = threading.Thread(
            target=llm_client.generate_structured,
            args=(ParsedCvProfile, _messages()),
            kwargs={"model": "model-a"},
        )
        thread_a.start()
        assert first_call_started.wait(timeout=2), "erster Aufruf ist nicht gestartet"

        thread_b = threading.Thread(
            target=llm_client.generate_structured,
            args=(ParsedCvProfile, _messages()),
            kwargs={"model": "model-b"},
        )
        thread_b.start()

        # Der zweite Aufruf muss blockieren, solange der erste den Lock hält -
        # er darf `client.chat` noch nicht erreicht haben.
        thread_b.join(timeout=0.3)
        assert call_log == ["start:model-a"], "zweiter Aufruf lief los, bevor der erste fertig war"

        release_first_call.set()
        thread_a.join(timeout=2)
        thread_b.join(timeout=2)

        assert call_log == ["start:model-a", "end:model-a", "start:model-b", "end:model-b"]


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
            "skills": json.dumps([{"name": "Python", "category": "Backend"}]),
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
        assert result.skills[0].name == "Python"
        assert result.skills[0].category == "Backend"
        assert mock_client.chat.call_count == 3

        # Der dritte Aufruf muss gegen ein anderes (abgeflachtes) Schema
        # laufen als die ersten beiden.
        first_format = mock_client.chat.call_args_list[0].kwargs["format"]
        fallback_format = mock_client.chat.call_args_list[2].kwargs["format"]
        assert first_format != fallback_format

    def test_nested_submodel_list_field_also_detected_as_structural(self, mock_client):
        """Verschachtelung eine Ebene tiefer (_NestedSubmodelResult.cv_content.experiences)."""
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

        result = llm_client.generate_structured(_NestedSubmodelResult, _messages())

        assert isinstance(result, _NestedSubmodelResult)
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


class TestTimeoutBudget:
    """Regression guard for the configured Ollama call timeout (see
    ce-debug-Untersuchung, 2026-08-18: CV-Upload-Spinner lief endlos).

    JSON-schema-constrained generation (used by every `generate_structured`
    call, including CV analysis) measured at ~2.2 tokens/second on
    CPU-only Ollama (no GPU passthrough in Docker) - a real multi-page CV
    routinely needs well over 120s of pure generation time. The previous
    120.0s default was too short and caused every non-trivial CV upload to
    fail with a timeout in production (confirmed via live backend logs).
    This locks in a floor generous enough for that measured throughput so
    a future change can't silently reintroduce the too-short default."""

    def test_ollama_timeout_default_is_generous_enough_for_cpu_inference(self):
        from app.core.config import Settings

        # Floor derived from live measurement: ~2.2 tok/s CPU throughput
        # under schema-constrained decoding means even a modest few-hundred-
        # token CV response needs several minutes, not 120s.
        assert Settings().OLLAMA_TIMEOUT_SECONDS >= 240.0


class TestResponseError:
    def test_ollama_response_error_raises_unavailable(self, mock_client):
        import ollama

        mock_client.chat.side_effect = ollama.ResponseError("model not found", 404)

        with pytest.raises(llm_client.LlmUnavailableError):
            llm_client.generate_structured(ParsedCvProfile, _messages())

        assert mock_client.chat.call_count == 1
