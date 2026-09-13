"""Tests für `app.services.translation_service` (U1 des Global-Language-
Unification-Plans: docs/plans/2026-09-13-003-feat-global-language-unification-plan.md).

Deckt die per-Feld-Fehlertoleranz ab: Ein fehlgeschlagenes Feld landet in
`errors`, erfolgreiche Felder in `translations` - der Originaltext geht nie
verloren (R9). Übersetzt wird ausschließlich de<->en über den bestehenden
Ollama-Client.
"""
from __future__ import annotations

import pytest

from app.services import translation_service
from app.services.llm_client import LlmUnavailableError, LlmValidationError
from app.services.translation_service import (
    TranslationResult,
    _TranslatedText,
    translate_fields,
)


def _translated(text: str) -> _TranslatedText:
    return _TranslatedText(translation=text)


class TestTranslateFieldsHappyPath:
    def test_translates_each_field_and_returns_per_field_results(self, mocker):
        mock_generate = mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            side_effect=[_translated("Experienced developer."), _translated("Developer")],
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
        assert mock_generate.call_count == 2

    def test_prompt_targets_the_requested_language_and_keeps_proper_nouns(self, mocker):
        mock_generate = mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_translated("Max works at Beispiel GmbH."),
        )

        translate_fields({"summary": "Max arbeitet bei Beispiel GmbH."}, source_language="de", target_language="en")

        model_cls, messages = mock_generate.call_args.args
        assert model_cls is _TranslatedText
        system_prompt = messages[0]["content"]
        assert "German" in system_prompt
        assert "English" in system_prompt
        assert "proper nouns" in system_prompt
        assert messages[1] == {"role": "user", "content": "Max arbeitet bei Beispiel GmbH."}


class TestTranslateFieldsErrorIsolation:
    def test_failed_field_appears_in_errors_and_other_fields_still_translate(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            side_effect=[
                _translated("Experienced developer."),
                LlmUnavailableError("Ollama ist nicht erreichbar"),
            ],
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

    def test_validation_failure_is_isolated_to_the_field(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            side_effect=LlmValidationError("schema mismatch"),
        )

        result = translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="en")

        assert result.translations == {}
        assert "summary" in result.errors

    def test_empty_model_translation_is_treated_as_a_field_error(self, mocker):
        # P2: Eine leere/whitespace-only Modellantwort darf das Originalfeld
        # nicht leeren - sie zählt als fehlgeschlagenes Feld (R9).
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            return_value=_translated("   "),
        )

        result = translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="en")

        assert result.translations == {}
        assert "summary" in result.errors

    def test_every_field_can_fail_independently(self, mocker):
        mocker.patch.object(
            translation_service.llm_client,
            "generate_structured",
            side_effect=LlmUnavailableError("Ollama ist nicht erreichbar"),
        )

        result = translate_fields(
            {"a": "eins", "b": "zwei"},
            source_language="de",
            target_language="en",
        )

        assert result.translations == {}
        assert set(result.errors) == {"a", "b"}


class TestTranslateFieldsShortCircuits:
    def test_same_language_returns_fields_unchanged_without_calling_ollama(self, mocker):
        mock_generate = mocker.patch.object(translation_service.llm_client, "generate_structured")

        result = translate_fields({"summary": "Erfahrener Entwickler."}, source_language="de", target_language="de")

        assert result.translations == {"summary": "Erfahrener Entwickler."}
        assert result.errors == {}
        mock_generate.assert_not_called()

    def test_empty_and_whitespace_values_pass_through_without_ollama(self, mocker):
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
