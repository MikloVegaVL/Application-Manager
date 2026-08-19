"""Tests für `app.services.pdf_service` (siehe U1 des Plans:
docs/plans/2026-08-19-001-feat-cv-only-email-attachment-plan.md).
"""
from __future__ import annotations

import pytest

from app.schemas.generation import TailoredCv
from app.schemas.master_profile import EducationEntry, ExperienceEntry
from app.services import pdf_service
from app.services.pdf_service import PdfRenderError

FULL_CV = TailoredCv(
    full_name="Max Mustermann",
    email="max@example.com",
    phone="+49 176 12345678",
    address="Musterstraße 1, 12345 Musterstadt",
    summary="Erfahrener Softwareentwickler mit Fokus auf Backend-Systeme.",
    experiences=[
        ExperienceEntry(
            company="Beispiel GmbH",
            role="Backend-Entwickler",
            start_date="2021",
            end_date="2024",
            description="Entwicklung und Wartung von APIs.",
        )
    ],
    education=[
        EducationEntry(
            institution="Universität Musterstadt",
            degree="B.Sc. Informatik",
            field_of_study="Informatik",
            start_date="2017",
            end_date="2021",
        )
    ],
    skills=["Python", "FastAPI", "SQL"],
)

EMPTY_CV = TailoredCv(
    full_name="Erika Musterfrau",
    email="erika@example.com",
    summary="",
    experiences=[],
    education=[],
    skills=[],
)


class TestRenderCvPdfHappyPath:
    def test_renders_a_full_cv_and_returns_non_empty_pdf_bytes(self):
        pdf_bytes = pdf_service.render_cv_pdf(FULL_CV)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_renders_a_cv_with_empty_experiences_education_and_skills(self):
        pdf_bytes = pdf_service.render_cv_pdf(EMPTY_CV)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0


class TestRenderCvPdfTemplateContent:
    def test_rendered_html_contains_no_cover_letter_markup(self, mocker):
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"

        pdf_service.render_cv_pdf(FULL_CV)

        mock_html_cls.assert_called_once()
        rendered_html = mock_html_cls.call_args.kwargs["string"]
        assert "cover-letter" not in rendered_html
        assert "letter-body" not in rendered_html
        assert "sender-block" not in rendered_html
        assert "recipient-block" not in rendered_html
        assert "date-block" not in rendered_html
        assert 'class="cv"' in rendered_html


class TestRenderCvPdfErrorHandling:
    def test_weasyprint_exception_surfaces_as_pdf_render_error(self, mocker):
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.side_effect = RuntimeError("boom")

        with pytest.raises(PdfRenderError):
            pdf_service.render_cv_pdf(FULL_CV)

    def test_empty_pdf_bytes_from_weasyprint_raises_pdf_render_error(self, mocker):
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b""

        with pytest.raises(PdfRenderError):
            pdf_service.render_cv_pdf(FULL_CV)
