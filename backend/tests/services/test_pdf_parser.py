"""Tests für `app.services.pdf_parser` (siehe U3 des CV-Builder-Plans:
docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md, sowie U3 des
früheren Ollama-Migrations-Plans:
docs/plans/2026-08-17-001-refactor-openai-to-ollama-migration-plan.md).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.master_profile import ParsedCvProfile, ParsedSkill
from app.services import pdf_parser
from app.services.llm_client import LlmUnavailableError, LlmValidationError
from app.services.pdf_parser import CvAnalysisError, PdfParsingError

VALID_PROFILE = ParsedCvProfile(
    full_name="Max Mustermann",
    email="max@example.com",
    phone=None,
    address=None,
    summary="Erfahrener Entwickler.",
    experiences=[],
    education=[],
    skills=[ParsedSkill(name="Python", category="Backend")],
    projects=[],
)


class TestAnalyzeCvTextHappyPath:
    def test_returns_validated_profile_from_helper(self, mocker):
        mock_generate = mocker.patch.object(
            pdf_parser.llm_client, "generate_structured", return_value=VALID_PROFILE
        )

        result = pdf_parser.analyze_cv_text("Lebenslauf-Text von Max Mustermann.")

        assert result is VALID_PROFILE
        mock_generate.assert_called_once()
        called_model_cls, called_messages = mock_generate.call_args[0]
        assert called_model_cls is ParsedCvProfile
        assert called_messages[0] == {"role": "system", "content": pdf_parser._SYSTEM_PROMPT}
        assert called_messages[1] == {
            "role": "user",
            "content": "Lebenslauf-Text von Max Mustermann.",
        }

    def test_uses_the_dedicated_cv_parsing_model_not_the_general_default(self, mocker):
        """CV parsing must pin its own, independently-tuned model rather than
        falling through to `settings.OLLAMA_MODEL` (the general default also
        used by `ai_generator.py` for application-content generation) -
        the two use cases have different speed/quality tradeoffs and must be
        able to move independently (see ce-debug-Untersuchung, 2026-08-18:
        qwen2.5:7b-instruct routinely timed out on CPU-only inference for
        real CVs; qwen2.5:3b-instruct was verified live to extract just as
        accurately, in a fraction of the time, using this exact prompt -
        but that verification covered CV parsing only, not application-
        content generation, so the swap must not silently affect the
        latter."""
        mock_generate = mocker.patch.object(
            pdf_parser.llm_client, "generate_structured", return_value=VALID_PROFILE
        )

        pdf_parser.analyze_cv_text("Lebenslauf-Text von Max Mustermann.")

        assert mock_generate.call_args.kwargs["model"] == settings.OLLAMA_MODEL_CV_PARSING


    def test_system_prompt_always_requests_english_output_and_skill_categories(self):
        """Der CV wird immer auf Englisch erzeugt (ce-debug, 2026-09-12): das
        Prompt muss die KI anweisen, alle Textwerte zu übersetzen, und für
        Skills eine Kategorie aus dem festen Wertebereich verlangen."""
        prompt = pdf_parser._SYSTEM_PROMPT

        assert "ENGLISH" in prompt
        for category in ("Frontend", "Backend", "Tools", "Soft Skills", "Other"):
            assert category in prompt


class TestAnalyzeCvTextValidationFailure:
    def test_llm_validation_error_becomes_cv_analysis_error(self, mocker):
        mocker.patch.object(
            pdf_parser.llm_client,
            "generate_structured",
            side_effect=LlmValidationError("schema mismatch"),
        )

        with pytest.raises(CvAnalysisError):
            pdf_parser.analyze_cv_text("irrelevanter Text")


class TestAnalyzeCvTextUnavailable:
    def test_llm_unavailable_error_becomes_cv_analysis_error(self, mocker):
        mocker.patch.object(
            pdf_parser.llm_client,
            "generate_structured",
            side_effect=LlmUnavailableError("Ollama ist nicht erreichbar"),
        )

        with pytest.raises(CvAnalysisError):
            pdf_parser.analyze_cv_text("irrelevanter Text")


class TestAnalyzeCvTextTruncation:
    def test_text_at_or_over_max_input_chars_is_truncated_before_helper_call(self, mocker):
        mock_generate = mocker.patch.object(
            pdf_parser.llm_client, "generate_structured", return_value=VALID_PROFILE
        )
        raw_text = "x" * (pdf_parser._MAX_INPUT_CHARS + 500)

        pdf_parser.analyze_cv_text(raw_text)

        _called_model_cls, called_messages = mock_generate.call_args[0]
        sent_content = called_messages[1]["content"]
        assert len(sent_content) == pdf_parser._MAX_INPUT_CHARS
        assert sent_content == raw_text[: pdf_parser._MAX_INPUT_CHARS]

    def test_text_exactly_at_max_input_chars_is_sent_unchanged(self, mocker):
        mock_generate = mocker.patch.object(
            pdf_parser.llm_client, "generate_structured", return_value=VALID_PROFILE
        )
        raw_text = "y" * pdf_parser._MAX_INPUT_CHARS

        pdf_parser.analyze_cv_text(raw_text)

        _called_model_cls, called_messages = mock_generate.call_args[0]
        assert called_messages[1]["content"] == raw_text


class TestExtractTextFromPdf:
    def test_raises_pdf_parsing_error_for_unreadable_bytes(self):
        with pytest.raises(PdfParsingError):
            pdf_parser.extract_text_from_pdf(b"not a real pdf")

    def test_extracts_text_from_a_minimal_valid_pdf(self):
        pypdf = pytest.importorskip("pypdf")
        from io import BytesIO

        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = BytesIO()
        writer.write(buffer)

        # Eine leere Seite enthält keinen Text -> erwartetermaßen kein
        # extrahierbarer Text, was den "leeres PDF"-Fehlerpfad abdeckt.
        with pytest.raises(PdfParsingError):
            pdf_parser.extract_text_from_pdf(buffer.getvalue())


class TestMissingFieldWarnings:
    """`missing_field_warnings` ersetzt das frühere, gleichnamige `_`-Helfer-
    Pendant in `app.api.profile` (dort für `upload_cv`) - mit U3 hierher
    verschoben und um `projects` erweitert, da der neue Parse-Endpunkt
    (`POST /cv-builder/parse`) Projekte mit ausgibt (R5)."""

    def test_full_profile_yields_no_warnings(self):
        full_profile = ParsedCvProfile(
            full_name="Max Mustermann",
            email="max@example.com",
            summary="Erfahrener Entwickler.",
            experiences=[{"company": "Acme GmbH", "role": "Entwickler"}],
            education=[{"institution": "TU Berlin", "degree": "B.Sc. Informatik"}],
            skills=[ParsedSkill(name="Python")],
            projects=[{"title": "Portfolio-Website", "description": "Persönliche Portfolio-Seite."}],
        )

        assert pdf_parser.missing_field_warnings(full_profile) == []

    def test_empty_profile_names_every_substantial_field_including_projects(self):
        empty = ParsedCvProfile(full_name="Max Mustermann", email="max@example.com")

        warnings = pdf_parser.missing_field_warnings(empty)

        assert "Kein Kurzprofil/Zusammenfassung gefunden." in warnings
        assert "Keine Berufserfahrung gefunden." in warnings
        assert "Keine Ausbildung gefunden." in warnings
        assert "Keine Skills gefunden." in warnings
        assert "Keine Projekte gefunden." in warnings

    def test_present_projects_suppress_only_the_projects_warning(self):
        parsed = ParsedCvProfile(
            full_name="Max Mustermann",
            email="max@example.com",
            projects=[{"title": "Portfolio-Website", "description": "Persönliche Portfolio-Seite."}],
        )

        warnings = pdf_parser.missing_field_warnings(parsed)

        assert "Keine Projekte gefunden." not in warnings
        # Andere leere Felder bleiben weiterhin gemeldet.
        assert "Keine Berufserfahrung gefunden." in warnings


class TestAnalyzeCvTextProjectsStructuralFailureFallback:
    """Regressionstest für `projects` als drittes `list[SubModel]`-Feld auf
    `ParsedCvProfile` (siehe docs/solutions/integration-issues/
    ollama-structured-output-nested-list-schema-validation-failure.md): Der
    generische Abflach-Fallback in `llm_client.generate_structured` deckt
    neue verschachtelte Listenfelder bereits ab, ohne dass `pdf_parser.py`
    dafür etwas Eigenes braucht - hier über `analyze_cv_text` (statt direkt
    über `generate_structured`, das test_llm_client.py bereits für
    `experiences`/`education` abdeckt) end-to-end gegen einen gemockten
    Ollama-Client geprüft, um sicherzustellen, dass die Verdrahtung über
    `pdf_parser.py` den Fallback nicht versehentlich umgeht."""

    def _response(self, payload: dict) -> SimpleNamespace:
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))

    def test_same_nested_projects_field_triggers_flattened_fallback(self, mocker):
        first_invalid = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [],
            "education": [],
            "skills": [],
            "projects": [{"description": "Persönliche Portfolio-Seite."}],  # "title" fehlt
        }
        second_invalid = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": [],
            "education": [],
            "skills": [],
            "projects": [
                {"title": "Portfolio-Website", "description": "Persönliche Portfolio-Seite."},
                {"title": "Zweites Projekt"},  # "description" fehlt
            ],
        }
        flat_payload = {
            "full_name": "Max Mustermann",
            "email": None,
            "phone": None,
            "address": None,
            "summary": None,
            "experiences": json.dumps([]),
            "education": json.dumps([]),
            "skills": json.dumps([]),
            "projects": json.dumps(
                [
                    {
                        "title": "Portfolio-Website",
                        "description": "Persönliche Portfolio-Seite.",
                        "start_date": None,
                        "end_date": None,
                        "link": None,
                    }
                ]
            ),
        }

        client_instance = mocker.MagicMock()
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = False
        client_instance.chat.side_effect = [
            self._response(first_invalid),
            self._response(second_invalid),
            self._response(flat_payload),
        ]
        mocker.patch.object(pdf_parser.llm_client.ollama, "Client", return_value=client_instance)

        result = pdf_parser.analyze_cv_text("Lebenslauf-Text von Max Mustermann.")

        assert isinstance(result, ParsedCvProfile)
        assert len(result.projects) == 1
        assert result.projects[0].title == "Portfolio-Website"
        assert client_instance.chat.call_count == 3
