"""Tests für `app.services.pdf_service` (U5 des Plans:
docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md).

Adaptiert vom vor Commit `97ac0b1` entfernten Testmodul gleichen Namens - an
das seitdem geänderte Schema angepasst (`SkillEntry`/`LanguageEntry` mit
Kompetenzgrad statt reiner Namens-Strings, `ProjectEntry`, Foto,
Template-Auswahl)."""
from __future__ import annotations

import pytest

from app.schemas.master_profile import EducationEntry, ExperienceEntry, LanguageEntry, ProjectEntry, SkillEntry
from app.services import pdf_service
from app.services.pdf_service import CV_TEMPLATES, PdfRenderError

TEMPLATE_IDS = [template["id"] for template in CV_TEMPLATES]


def _full_content() -> dict:
    return dict(
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
        skills=[SkillEntry(name="Python", level="Experte"), SkillEntry(name="SQL", level="Gut")],
        languages=[LanguageEntry(name="Deutsch", level="C2"), LanguageEntry(name="Englisch", level="B2")],
        projects=[
            ProjectEntry(
                title="Portfolio-Website",
                description="Persönliche Portfolio-Seite mit Projektübersicht.",
                start_date="2022",
                end_date=None,
                link="https://example.com/portfolio",
            )
        ],
        photo_path=None,
    )


def _empty_content() -> dict:
    return dict(
        full_name="Erika Musterfrau",
        email="erika@example.com",
        phone=None,
        address=None,
        summary="",
        experiences=[],
        education=[],
        skills=[],
        languages=[],
        projects=[],
        photo_path=None,
    )


class TestRenderCvPdfHappyPath:
    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_renders_a_full_cv_and_returns_non_empty_pdf_bytes(self, template_id):
        pdf_bytes = pdf_service.render_cv_pdf(template_id=template_id, **_full_content())

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_renders_a_cv_with_empty_sections(self, template_id):
        pdf_bytes = pdf_service.render_cv_pdf(template_id=template_id, **_empty_content())

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_renders_with_photo(self, tmp_path):
        photo_path = tmp_path / "photo.png"
        photo_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
            b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        content = _full_content()
        content["photo_path"] = str(photo_path)

        pdf_bytes = pdf_service.render_cv_pdf(template_id="classic", **content)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0


class TestRenderCvPdfTemplateContent:
    def test_no_photo_omits_the_photo_slot_instead_of_a_broken_img(self, mocker):
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"

        pdf_service.render_cv_pdf(template_id="classic", **_full_content())

        rendered_html = mock_html_cls.call_args.kwargs["string"]
        assert "<img" not in rendered_html

    def test_free_text_html_is_escaped_not_rendered_as_live_markup(self, mocker):
        """Autoescape-Regressionstest (KTD6): ein Freitextfeld mit
        HTML-ähnlichem Inhalt darf im Zwischen-HTML nur als literaler,
        escapter Text auftauchen - niemals als aktives Markup."""
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"

        content = _full_content()
        content["summary"] = "<script>alert(1)</script>"

        pdf_service.render_cv_pdf(template_id="classic", **content)

        rendered_html = mock_html_cls.call_args.kwargs["string"]
        assert "<script>alert(1)</script>" not in rendered_html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered_html

    def test_url_fetcher_restricts_to_local_resources(self, mocker):
        """KTD6: der WeasyPrint-Aufruf muss mit einem `url_fetcher`
        konfiguriert sein, der ausschließlich lokale Ressourcen (`file://`,
        `data:`) lädt, damit CV-Inhalt (Freitext/Projekt-Links) keine
        ausgehenden Requests auslösen kann."""
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"

        pdf_service.render_cv_pdf(template_id="classic", **_full_content())

        url_fetcher = mock_html_cls.call_args.kwargs["url_fetcher"]
        with pytest.raises(ValueError):
            url_fetcher("https://example.com/x.png")


class TestRenderCvPdfErrorHandling:
    def test_unknown_template_id_raises(self):
        with pytest.raises(Exception):
            pdf_service.render_cv_pdf(template_id="does-not-exist", **_empty_content())

    def test_weasyprint_exception_surfaces_as_pdf_render_error(self, mocker):
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.side_effect = RuntimeError("boom")

        with pytest.raises(PdfRenderError):
            pdf_service.render_cv_pdf(template_id="classic", **_full_content())

    def test_empty_pdf_bytes_from_weasyprint_raises_pdf_render_error(self, mocker):
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b""

        with pytest.raises(PdfRenderError):
            pdf_service.render_cv_pdf(template_id="classic", **_full_content())
