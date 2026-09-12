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
        berufsbezeichnung="Backend-Entwickler",
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


class TestGroupSkills:
    """`group_skills` verdichtet die flache Skill-Liste zu Kategorien (siehe
    R9-Folge) - eine lange Liste wird so auf wenige Zeilen reduziert."""

    def test_groups_by_category_preserving_first_appearance(self):
        groups = pdf_service.group_skills(
            [
                SkillEntry(name="Angular", level="Experte", category="Frontend"),
                SkillEntry(name="Python", level="Gut", category="Backend"),
                SkillEntry(name="React", level="Gut", category="Frontend"),
            ]
        )

        assert [group["category"] for group in groups] == ["Frontend", "Backend"]
        assert [skill["name"] for skill in groups[0]["skills"]] == ["Angular", "React"]

    def test_group_level_is_the_highest_in_the_group_and_gets_an_english_label(self):
        groups = pdf_service.group_skills(
            [
                SkillEntry(name="A", level="Grundkenntnisse", category="Tools"),
                SkillEntry(name="B", level="Experte", category="Tools"),
                SkillEntry(name="C", level="Gut", category="Tools"),
            ]
        )

        assert groups[0]["level"] == "Experte"
        assert groups[0]["level_label"] == "Expert"

    def test_skills_without_a_category_fall_into_other(self):
        groups = pdf_service.group_skills([SkillEntry(name="Legacy", level="Gut")])

        assert groups[0]["category"] == "Other"
        assert groups[0]["level_label"] == "Good"

    def test_empty_skill_list_yields_no_groups(self):
        assert pdf_service.group_skills([]) == []


class TestMultiPageFragmentation:
    def test_template_1_keeps_the_name_on_page_1_when_the_sidebar_overflows(self):
        """Regression (ce-debug, 2026-09-12): Template 1 nutzte `display:flex`
        für die zwei Spalten. WeasyPrint fragmentiert ein Row-Flex-Container
        nicht seitenweise - eine Sidebar, die länger als eine Seite ist, schob
        die komplette Hauptspalte inkl. Name auf Seite 2. `display:table`
        hält beide Spalten ab Seite 1 nebeneinander."""
        content = _empty_content()
        content["summary"] = "Summary text that belongs on the first page."
        # Sidebar-Inhalt deutlich über eine Seite hinaus (Sprachen + Ausbildung).
        content["languages"] = [
            LanguageEntry(name=f"Language {i}", level="B2") for i in range(60)
        ]
        content["education"] = [
            EducationEntry(
                institution=f"University {i}",
                degree="B.Sc.",
                field_of_study="Computer Science",
                start_date="2010",
                end_date="2014",
            )
            for i in range(40)
        ]

        pdf_bytes = pdf_service.render_cv_pdf(template_id="template-1", **content)

        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) > 1
        first_page_text = reader.pages[0].extract_text() or ""
        assert "erika musterfrau" in first_page_text.lower()


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


class TestRenderCvPdfPreviewMode:
    def _capture(self, mocker, **kwargs) -> str:
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"
        pdf_service.render_cv_pdf(**kwargs)
        return mock_html_cls.call_args.kwargs["string"]

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_preview_renders_all_canonical_sections(self, mocker, template_id):
        rendered = self._capture(mocker, template_id=template_id, preview=True, **_empty_content())

        for heading in ("Profile", "Experience", "Education", "Skills", "Languages", "Projects"):
            assert heading in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_preview_fills_empty_sections_with_muted_sample_content(self, mocker, template_id):
        rendered = self._capture(mocker, template_id=template_id, preview=True, **_empty_content())

        assert "Experienced professional" in rendered
        assert "Example GmbH" in rendered
        assert 'class="ph"' in rendered

    def test_export_omits_sample_content_even_when_a_sample_is_passed(self, mocker):
        rendered = self._capture(
            mocker,
            template_id="classic",
            preview=False,
            sample=pdf_service.SAMPLE,
            **_empty_content(),
        )

        assert "Example GmbH" not in rendered
        assert "Experience" not in rendered
        # R9: auch die leere `Profile`-Überschrift fehlt im Export.
        assert "Profile" not in rendered

    def test_preview_keeps_real_entry_and_fills_only_a_blank_sub_field(self, mocker):
        content = _empty_content()
        content["experiences"] = [
            ExperienceEntry(
                company="Acme GmbH",
                role="Entwickler",
                start_date="2020",
                end_date=None,
                description=None,
            )
        ]

        rendered = self._capture(mocker, template_id="classic", preview=True, **content)

        assert "Acme GmbH" in rendered
        assert "Entwickler" in rendered
        assert "Description of the role" in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_berufsbezeichnung_renders_under_the_name(self, mocker, template_id):
        content = _empty_content()
        content["berufsbezeichnung"] = "Frontend Developer"

        rendered = self._capture(mocker, template_id=template_id, preview=False, **content)

        assert "Frontend Developer" in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_empty_berufsbezeichnung_shows_sample_in_preview(self, mocker, template_id):
        rendered = self._capture(mocker, template_id=template_id, preview=True, **_empty_content())

        assert pdf_service.SAMPLE["berufsbezeichnung"] in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_empty_berufsbezeichnung_absent_in_export(self, mocker, template_id):
        rendered = self._capture(mocker, template_id=template_id, preview=False, **_empty_content())

        assert pdf_service.SAMPLE["berufsbezeichnung"] not in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_preview_without_photo_shows_placeholder(self, mocker, template_id):
        rendered = self._capture(mocker, template_id=template_id, preview=True, **_empty_content())

        assert "photo--placeholder" in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_export_without_photo_omits_img(self, mocker, template_id):
        rendered = self._capture(mocker, template_id=template_id, preview=False, **_empty_content())

        assert "<img" not in rendered

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_preview_renders_real_pdf_bytes(self, template_id):
        """Vorschau läuft (anders als die HTML-Assertions oben) durch echtes
        WeasyPrint - ein kaputtes Preview-Konstrukt darf nicht nur im Mock
        bestehen."""
        pdf_bytes = pdf_service.render_cv_pdf(template_id=template_id, preview=True, **_empty_content())

        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 0
