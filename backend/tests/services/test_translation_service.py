"""Tests für `app.services.translation_service` (U3 des CV-Translation-
Batching-Plans: docs/plans/2026-09-13-004-perf-cv-translation-batching-plan.md).

Seit dem Batching übersetzt der Service die gesamte Feldzuordnung in EINEM
`generate_structured`-Aufruf (statt einem pro Feld) und rekonstruiert die
per-Feld-Ergebnisse durch Abgleich der zurückgegebenen Schlüssel mit den
angefragten. Ein fehlgeschlagenes Feld landet weiterhin in `errors` - der
Originaltext geht nie verloren (R4). Übersetzt wird ausschließlich de<->en
über den bestehenden Ollama-Client.
"""
from __future__ import annotations

import json

import pytest

from app.services import translation_service
from app.services.llm_client import LlmUnavailableError, LlmValidationError
from app.services.translation_service import (
    TranslationResult,
    _BatchTranslation,
    translate_fields,
)


def _batch(translations: dict[str, str]) -> _BatchTranslation:
    return _BatchTranslation(translations=translations)


class TestTranslateFieldsBatching:
    def test_translates_whole_map_in_one_call(self, mocker):
        mock_generate = mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch(
                {
                    "summary": "Experienced developer.",
                    "berufsbezeichnung": "Developer",
                }
            ),
        )

        result = translate_fields(
            {"summary": "Erfahrener Entwickler.", "berufsbezeichnung": "Entwickler"},
            source_language="de",
            target_language="en",
        )

        assert isinstance(result, TranslationResult)
        assert result.translations == {
            "summary": "Experienced developer.",
            "berufsbezeichnung": "Developer",
        }
        assert result.errors == {}
        assert mock_generate.call_count == 1

    def test_prompt_targets_language_keeps_proper_nouns_and_sends_field_map(self, mocker):
        mock_generate = mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch({"summary": "Max works at Beispiel GmbH."}),
        )

        translate_fields(
            {"summary": "Max arbeitet bei Beispiel GmbH."},
            source_language="de",
            target_language="en",
        )

        model_cls, messages = mock_generate.call_args.args
        assert model_cls is _BatchTranslation
        system_prompt = messages[0]["content"]
        assert "German" in system_prompt
        assert "English" in system_prompt
        assert "proper nouns" in system_prompt
        assert json.loads(messages[1]["content"]) == {"summary": "Max arbeitet bei Beispiel GmbH."}

    def test_batch_call_passes_context_and_output_budget(self, mocker):
        mock_generate = mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch({"summary": "Experienced developer."}),
        )

        translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="en")

        assert mock_generate.call_args.kwargs["options"] == {"num_ctx": 8192, "num_predict": 2048}


class TestTranslateFieldsErrorIsolation:
    def test_missing_key_is_an_error_and_other_fields_translate(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch({"summary": "Experienced developer."}),
        )

        result = translate_fields(
            {"summary": "Erfahrener Entwickler.", "berufsbezeichnung": "Entwickler"},
            source_language="de",
            target_language="en",
        )

        assert result.translations == {"summary": "Experienced developer."}
        assert "berufsbezeichnung" in result.errors
        # Ein fehlgeschlagenes Feld darf nie in beiden Maps stehen.
        assert "berufsbezeichnung" not in result.translations

    def test_blank_value_is_an_error(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch({"summary": "   "}),
        )

        result = translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="en")

        assert result.translations == {}
        assert "summary" in result.errors

    def test_unknown_extra_key_is_ignored(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch({"summary": "Experienced developer.", "bogus": "ignored"}),
        )

        result = translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="en")

        assert result.translations == {"summary": "Experienced developer."}
        assert result.errors == {}

    @pytest.mark.parametrize(
        "exc",
        [
            LlmValidationError("schema mismatch"),
            LlmUnavailableError("Ollama ist nicht erreichbar"),
        ],
    )
    def test_whole_batch_failure_errors_every_field(self, mocker, exc):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            side_effect=exc,
        )

        result = translate_fields(
            {"a": "eins", "b": "zwei"},
            source_language="de",
            target_language="en",
        )

        assert result.translations == {}
        assert set(result.errors) == {"a", "b"}

    def test_whole_batch_failure_keeps_blank_passthrough_out_of_errors(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            side_effect=LlmUnavailableError("Ollama ist nicht erreichbar"),
        )

        result = translate_fields(
            {"summary": "Erfahrener Entwickler.", "berufsbezeichnung": "   "},
            source_language="de",
            target_language="en",
        )

        # Nur der nicht-leere Batch-Eintrag ist ein Fehler; der leere Wert
        # wurde vor dem Modellaufruf unverändert durchgereicht (R4).
        assert result.translations == {"berufsbezeichnung": "   "}
        assert set(result.errors) == {"summary"}

    def test_blank_and_non_blank_are_partitioned_in_one_call(self, mocker):
        mock_generate = mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_batch({"summary": "Experienced developer."}),
        )

        result = translate_fields(
            {"summary": "Erfahrener Entwickler.", "berufsbezeichnung": "   "},
            source_language="de",
            target_language="en",
        )

        assert result.translations == {
            "summary": "Experienced developer.",
            "berufsbezeichnung": "   ",
        }
        assert result.errors == {}
        assert mock_generate.call_count == 1
        assert json.loads(mock_generate.call_args.args[1][1]["content"]) == {"summary": "Erfahrener Entwickler."}


class TestTranslateFieldsShortCircuits:
    def test_same_language_returns_fields_unchanged_without_calling_ollama(self, mocker):
        mock_generate = mocker.patch.object(translation_service.llm_client, "generate_structured")

        result = translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="de")

        assert result.translations == {"summary": "Erfahrener Entwickler."}
        assert result.errors == {}
        mock_generate.assert_not_called()

    def test_all_blank_values_pass_through_without_ollama(self, mocker):
        mock_generate = mocker.patch.object(translation_service.llm_client, "generate_structured")

        result = translate_fields(
            {"summary": "", "berufsbezeichnung": "   "},
            source_language="de",
            target_language="en",
        )

        assert result.translations == {"summary": "", "berufsbezeichnung": "   "}
        assert result.errors == {}
        mock_generate.assert_not_called()

    def test_empty_field_mapping_returns_empty_result(self, mocker):
        mock_generate = mocker.patch.object(translation_service.llm_client, "generate_structured")

        result = translate_fields({}, source_language="de", target_language="en")

        assert result.translations == {}
        assert result.errors == {}
        mock_generate.assert_not_called()


class TestTranslateFieldsUnsupportedPair:
    def test_unsupported_language_pair_raises_value_error(self):
        with pytest.raises(ValueError):
            translate_fields({"summary": "text"}, source_language="de", target_language="fr")
