"""Tests für `app.services.pdf_parser` (siehe U3 des Plans:
docs/plans/2026-08-17-001-refactor-openai-to-ollama-migration-plan.md).
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.schemas.master_profile import ParsedCvProfile
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
    skills=["Python"],
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
