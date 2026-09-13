"""Tests für `app.services.pdf_service` (U5 des Plans:
docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md).

Adaptiert vom vor Commit `97ac0b1` entfernten Testmodul gleichen Namens - an
das seitdem geänderte Schema angepasst (`SkillEntry`/`LanguageEntry` mit
Kompetenzgrad statt reiner Namens-Strings, `ProjectEntry`, Foto,
Template-Auswahl)."""
from __future__ import annotations

from pathlib import Path

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


def _rendered_html(mocker, **kwargs) -> str:
    """Rendert `render_cv_pdf(**kwargs)` mit gemocktem WeasyPrint und gibt das
    an `HTML(string=...)` übergebene Zwischen-HTML zurück - gemeinsamer Helper
    für die Template-spezifischen Per-Skill-Rendering-Testklassen unten."""
    mock_html_cls = mocker.patch.object(pdf_service, "HTML")
    mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"
    pdf_service.render_cv_pdf(**kwargs)
    return mock_html_cls.call_args.kwargs["string"]


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


class TestSkillLevelBlocksAndLanguageLevelDots:
    """R3/R4/R6/KTD1: die 4-stufige Skill-Skala wird serverseitig auf einen
    5-Block-Balken abgebildet, die CEFR-Stufe auf den bestehenden
    6-Punkte-Indikator - beides zentral in `pdf_service`, nicht länger lokal
    je Vorlage dupliziert."""

    def test_skill_level_blocks_maps_all_four_tiers(self):
        assert pdf_service._SKILL_LEVEL_BLOCKS == {
            "Grundkenntnisse": 2,
            "Gut": 3,
            "Sehr gut": 4,
            "Experte": 5,
        }

    def test_language_level_dots_maps_all_six_cefr_tiers(self):
        assert pdf_service._LANGUAGE_LEVEL_DOTS == {
            "A1": 1,
            "A2": 2,
            "B1": 3,
            "B2": 4,
            "C1": 5,
            "C2": 6,
        }

    def test_no_grouping_helpers_or_state_remain(self):
        """KTD2: `group_skills`/`skill_groups`/`sample_skill_groups` und die
        dafür genutzte Sortier-/Fallback-Kategorie sind vollständig entfernt -
        jede Vorlage iteriert `skills`/`sample.skills` direkt, ohne
        Kategorie-Gruppierung."""
        assert not hasattr(pdf_service, "group_skills")
        assert not hasattr(pdf_service, "_SKILL_LEVEL_ORDER")
        assert not hasattr(pdf_service, "_OTHER_SKILL_CATEGORY")


class TestRenderCvPdfSkillsAndLanguagesContext:
    """`render_cv_pdf` reichert jeden Skill/jede Sprache serverseitig mit den
    Anzeige-Metadaten für den 5-Block-Balken bzw. den 6-Punkte-CEFR-Indikator
    an (KTD1), statt dass die Vorlagen die Zuordnung lokal duplizieren."""

    def _rendered_kwargs(self, mocker, **kwargs) -> dict:
        mock_template = mocker.MagicMock()
        mock_template.render.return_value = "<html></html>"
        mocker.patch.object(pdf_service._env, "get_template", return_value=mock_template)
        mock_html_cls = mocker.patch.object(pdf_service, "HTML")
        mock_html_cls.return_value.write_pdf.return_value = b"%PDF-1.4 fake bytes"

        pdf_service.render_cv_pdf(**kwargs)

        return mock_template.render.call_args.kwargs

    def test_skills_ctx_carries_level_blocks_and_english_level_label(self, mocker):
        content = _full_content()
        content["skills"] = [
            SkillEntry(name="Python", level="Experte"),
            SkillEntry(name="SQL", level="Grundkenntnisse"),
        ]

        kwargs = self._rendered_kwargs(mocker, template_id="classic", **content)

        skills_ctx = kwargs["skills_ctx"]
        assert [skill["name"] for skill in skills_ctx] == ["Python", "SQL"]
        assert skills_ctx[0]["level_blocks"] == 5
        assert skills_ctx[0]["level_label"] == "Expert"
        assert skills_ctx[1]["level_blocks"] == 2
        assert skills_ctx[1]["level_label"] == "Basic"

    def test_languages_ctx_carries_level_dots(self, mocker):
        content = _full_content()
        content["languages"] = [
            LanguageEntry(name="Deutsch", level="C2"),
            LanguageEntry(name="Englisch", level="B1"),
        ]

        kwargs = self._rendered_kwargs(mocker, template_id="classic", **content)

        languages_ctx = kwargs["languages_ctx"]
        assert [lang["name"] for lang in languages_ctx] == ["Deutsch", "Englisch"]
        assert languages_ctx[0]["level_dots"] == 6
        assert languages_ctx[1]["level_dots"] == 3

    def test_sample_skills_and_languages_ctx_populated_in_preview(self, mocker):
        kwargs = self._rendered_kwargs(
            mocker, template_id="classic", preview=True, **_empty_content()
        )

        assert kwargs["sample_skills_ctx"], "preview should populate sample skills context"
        assert all("level_blocks" in skill for skill in kwargs["sample_skills_ctx"])
        assert kwargs["sample_languages_ctx"], "preview should populate sample languages context"
        assert all("level_dots" in lang for lang in kwargs["sample_languages_ctx"])

    def test_sample_skills_and_languages_ctx_empty_outside_preview(self, mocker):
        kwargs = self._rendered_kwargs(
            mocker, template_id="classic", preview=False, **_empty_content()
        )

        assert kwargs["sample_skills_ctx"] == []
        assert kwargs["sample_languages_ctx"] == []

    def test_context_no_longer_carries_removed_grouping_keys(self, mocker):
        kwargs = self._rendered_kwargs(mocker, template_id="classic", **_full_content())

        assert "skill_groups" not in kwargs
        assert "sample_skill_groups" not in kwargs


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

    def test_template_2_keeps_the_header_band_on_page_1_when_the_sidebar_overflows(self):
        """Wie oben (template-1), aber für Template 2: das Kopfband liegt
        VOR der Zwei-Spalten-Tabelle, muss also unabhängig davon auf Seite 1
        bleiben, wenn die Sidebar (Sprachen + Ausbildung) über eine Seite
        hinausragt."""
        content = _empty_content()
        content["summary"] = "Summary text that belongs on the first page."
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

        pdf_bytes = pdf_service.render_cv_pdf(template_id="template-2", **content)

        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) > 1
        first_page_text = reader.pages[0].extract_text() or ""
        assert "erika musterfrau" in first_page_text.lower()

    def test_template_3_keeps_the_header_on_page_1_when_the_sidebar_overflows(self):
        """Wie oben (template-1/template-2), aber für Template 3: der Header
        (Foto/Name/Berufsbezeichnung) liegt VOR der Zwei-Spalten-Tabelle,
        muss also unabhängig davon auf Seite 1 bleiben, wenn die Sidebar
        (Sprachen + Ausbildung) über eine Seite hinausragt. Anders als
        template-2.html liegt die Sidebar hier rechts (schmal) statt links,
        aber `display:table` fragmentiert unabhängig von der Spaltenreihenfolge
        korrekt."""
        content = _empty_content()
        content["summary"] = "Summary text that belongs on the first page."
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

        pdf_bytes = pdf_service.render_cv_pdf(template_id="template-3", **content)

        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) > 1
        first_page_text = reader.pages[0].extract_text() or ""
        assert "erika musterfrau" in first_page_text.lower()

    def test_template_4_keeps_the_name_on_page_1_when_the_sidebar_overflows(self):
        """Wie oben (template-1/2/3), aber für Template 4: die volle Höhe
        einnehmende Sidebar (Foto/Kontakt/Skills/Sprachen/Ausbildung) liegt
        NEBEN der Hauptspalte in derselben `display:table`-Zeile - eine
        Sidebar, die länger als eine Seite ist, darf die Hauptspalte inkl.
        Name nicht komplett auf Seite 2 schieben."""
        content = _empty_content()
        content["summary"] = "Summary text that belongs on the first page."
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

        pdf_bytes = pdf_service.render_cv_pdf(template_id="template-4", **content)

        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) > 1
        first_page_text = reader.pages[0].extract_text() or ""
        assert "erika musterfrau" in first_page_text.lower()


class TestClassicPerSkillRendering:
    """R5: Classic listet jeden Skill einzeln als Klartext mit englischem
    Kompetenzgrad-Suffix, ohne Kategorie und ohne Balken - für echte wie für
    Beispiel-(Preview-)Skills."""

    def test_real_skills_render_individually_as_plain_text_with_english_level(self, mocker):
        content = _full_content()
        content["skills"] = [
            SkillEntry(name="Python", level="Experte"),
            SkillEntry(name="SQL", level="Gut"),
        ]

        rendered = _rendered_html(mocker, template_id="classic", **content)

        assert "Python <span class=\"tag__level\">&mdash; Expert</span>" in rendered
        assert "SQL <span class=\"tag__level\">&mdash; Good</span>" in rendered
        assert "tag__category" not in rendered
        assert "class=\"bar\"" not in rendered

    def test_sample_skills_render_individually_in_preview(self, mocker):
        rendered = _rendered_html(
            mocker, template_id="classic", preview=True, **_empty_content()
        )

        sample_skill = pdf_service.SAMPLE["skills"][0]
        assert sample_skill["name"] in rendered
        assert "tag__category" not in rendered


class TestTemplate1PerSkillRendering:
    """R3/R4: Template 1 rendert jeden Skill als eigene Zeile mit einem
    5-Block-Balken statt einer Kategorie-Gruppierung mit Breitenbalken."""

    def test_renders_five_span_bar_with_correct_filled_count_per_level(self, mocker):
        content = _full_content()
        content["skills"] = [
            SkillEntry(name="Python", level="Experte"),
            SkillEntry(name="SQL", level="Grundkenntnisse"),
        ]

        rendered = _rendered_html(mocker, template_id="template-1", **content)

        # Experte -> 5/5 gefüllt (kein "off"), Grundkenntnisse -> 2/5 gefüllt (3x "off").
        assert '<i></i><i></i><i></i><i></i><i></i>' in rendered
        assert '<i></i><i></i><i class="off"></i><i class="off"></i><i class="off"></i>' in rendered

    def test_no_category_or_grouping_markup_remains(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]

        rendered = _rendered_html(mocker, template_id="template-1", **content)

        assert "skill-row__head" not in rendered
        assert "skill-row__names" not in rendered
        assert "category" not in rendered.lower()

    def test_ktd10_hidden_level_text_present_for_skills_and_languages(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]
        content["languages"] = [LanguageEntry(name="Deutsch", level="C2")]

        rendered = _rendered_html(mocker, template_id="template-1", **content)

        assert '<span class="sr-only">Expert</span>' in rendered
        assert '<span class="sr-only">C2</span>' in rendered

    def test_language_dots_source_from_languages_ctx_not_a_local_map(self, mocker):
        content = _full_content()
        content["languages"] = [LanguageEntry(name="Deutsch", level="B1")]

        rendered = _rendered_html(mocker, template_id="template-1", **content)

        assert "lang_dots" not in rendered
        # B1 -> 3/6 gefüllt.
        assert '<i></i><i></i><i></i><i class="off"></i><i class="off"></i><i class="off"></i>' in rendered


class TestTemplate2PerSkillRendering:
    """R3/R4/R6: Template 2 rendert jeden Skill als eigene Zeile mit einem
    5-Block-Balken und jede Sprache mit dem 6-Punkte-CEFR-Indikator - wie
    Template 1, nur im navy/amber-Farbschema der Referenzvorlage."""

    def test_renders_five_block_bar_with_correct_filled_count_per_level(self, mocker):
        content = _full_content()
        content["skills"] = [
            SkillEntry(name="Python", level="Experte"),
            SkillEntry(name="SQL", level="Grundkenntnisse"),
        ]

        rendered = _rendered_html(mocker, template_id="template-2", **content)

        # Experte -> 5/5 gefüllt (kein "off"), Grundkenntnisse -> 2/5 gefüllt (3x "off").
        assert '<i></i><i></i><i></i><i></i><i></i>' in rendered
        assert '<i></i><i></i><i class="off"></i><i class="off"></i><i class="off"></i>' in rendered

    def test_ktd10_hidden_level_text_present_for_skills_and_languages(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]
        content["languages"] = [LanguageEntry(name="Deutsch", level="C2")]

        rendered = _rendered_html(mocker, template_id="template-2", **content)

        assert '<span class="sr-only">Expert</span>' in rendered
        assert '<span class="sr-only">C2</span>' in rendered

    def test_language_dots_reflect_the_entered_cefr_level(self, mocker):
        content = _full_content()
        content["languages"] = [LanguageEntry(name="Deutsch", level="B2")]

        rendered = _rendered_html(mocker, template_id="template-2", **content)

        # B2 -> 4/6 gefüllt.
        assert (
            '<i></i><i></i><i></i><i></i><i class="off"></i><i class="off"></i>' in rendered
        )

    def test_no_category_or_grouping_markup_remains(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]

        rendered = _rendered_html(mocker, template_id="template-2", **content)

        assert "category" not in rendered.lower()


class TestTemplate3PerSkillRendering:
    """R3/R4/R6: Template 3 rendert jeden Skill als eigene Zeile mit einem
    5-Block-Balken und jede Sprache mit dem 6-Punkte-CEFR-Indikator - wie
    Template 1/2, nur im rot-akzentuierten Farbschema der Referenzvorlage
    mit Hauptspalte links/Sidebar rechts."""

    def test_renders_five_block_bar_with_correct_filled_count_per_level(self, mocker):
        content = _full_content()
        content["skills"] = [
            SkillEntry(name="Python", level="Experte"),
            SkillEntry(name="SQL", level="Grundkenntnisse"),
        ]

        rendered = _rendered_html(mocker, template_id="template-3", **content)

        # Experte -> 5/5 gefüllt (kein "off"), Grundkenntnisse -> 2/5 gefüllt (3x "off").
        assert '<i></i><i></i><i></i><i></i><i></i>' in rendered
        assert '<i></i><i></i><i class="off"></i><i class="off"></i><i class="off"></i>' in rendered

    def test_ktd10_hidden_level_text_present_for_skills_and_languages(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]
        content["languages"] = [LanguageEntry(name="Deutsch", level="C2")]

        rendered = _rendered_html(mocker, template_id="template-3", **content)

        assert '<span class="sr-only">Expert</span>' in rendered
        assert '<span class="sr-only">C2</span>' in rendered

    def test_language_dots_reflect_the_entered_cefr_level(self, mocker):
        content = _full_content()
        content["languages"] = [LanguageEntry(name="Deutsch", level="B2")]

        rendered = _rendered_html(mocker, template_id="template-3", **content)

        # B2 -> 4/6 gefüllt.
        assert (
            '<i></i><i></i><i></i><i></i><i class="off"></i><i class="off"></i>' in rendered
        )

    def test_no_category_or_grouping_markup_remains(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]

        rendered = _rendered_html(mocker, template_id="template-3", **content)

        assert "category" not in rendered.lower()

    def test_berufsbezeichnung_renders_beneath_the_name_in_header(self, mocker):
        """Die statische Referenzvorlage zeigt bereits eine Rollen-/Job-Title-
        Zeile unter dem Namen (KTD7/Plan-Annahme: Berufsbezeichnung rendert
        in allen neuen Vorlagen konsistent unter dem Namen)."""
        content = _full_content()
        content["berufsbezeichnung"] = "Full-Stack Developer"

        rendered = _rendered_html(mocker, template_id="template-3", **content)

        assert '<div class="header__name">Max Mustermann</div>' in rendered
        assert "Full-Stack Developer" in rendered
        name_pos = rendered.index('<div class="header__name">')
        title_pos = rendered.index('<div class="header__title">')
        assert name_pos < title_pos


class TestTemplate4PerSkillRendering:
    """R3/R4/R6: Template 4 rendert jeden Skill als eigene Zeile mit einem
    5-Block-Balken und jede Sprache mit dem 6-Punkte-CEFR-Indikator - wie
    Template 1/2/3, nur im teal/navy-Farbschema der Referenzvorlage mit
    volle-Höhe-Sidebar und zentriertem Namen in der Hauptspalte."""

    def test_renders_five_block_bar_with_correct_filled_count_per_level(self, mocker):
        content = _full_content()
        content["skills"] = [
            SkillEntry(name="Python", level="Experte"),
            SkillEntry(name="SQL", level="Grundkenntnisse"),
        ]

        rendered = _rendered_html(mocker, template_id="template-4", **content)

        # Experte -> 5/5 gefüllt (kein "off"), Grundkenntnisse -> 2/5 gefüllt (3x "off").
        assert '<i></i><i></i><i></i><i></i><i></i>' in rendered
        assert '<i></i><i></i><i class="off"></i><i class="off"></i><i class="off"></i>' in rendered

    def test_ktd10_hidden_level_text_present_for_skills_and_languages(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]
        content["languages"] = [LanguageEntry(name="Deutsch", level="C2")]

        rendered = _rendered_html(mocker, template_id="template-4", **content)

        assert '<span class="sr-only">Expert</span>' in rendered
        assert '<span class="sr-only">C2</span>' in rendered

    def test_language_dots_reflect_the_entered_cefr_level(self, mocker):
        content = _full_content()
        content["languages"] = [LanguageEntry(name="Deutsch", level="B2")]

        rendered = _rendered_html(mocker, template_id="template-4", **content)

        # B2 -> 4/6 gefüllt.
        assert (
            '<i></i><i></i><i></i><i></i><i class="off"></i><i class="off"></i>' in rendered
        )

    def test_no_category_or_grouping_markup_remains(self, mocker):
        content = _full_content()
        content["skills"] = [SkillEntry(name="Python", level="Experte")]

        rendered = _rendered_html(mocker, template_id="template-4", **content)

        assert "category" not in rendered.lower()

    def test_language_dots_are_circular_not_bars(self):
        """R6/Product-Contract-Key-Decision: Sprachen bekommen den
        6-Punkte-Kreis-Indikator, nicht die rechteckige Balkenform der
        Skill-Blöcke - auch wenn die statische Referenzvorlage für Template 4
        an dieser Stelle bereits Kreise nutzt, wird das hier explizit
        gegengeprüft, damit eine künftige Änderung die Regression aus U5
        (Template 3, Balken statt Kreise) nicht wiederholt."""
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "app"
            / "templates"
            / "cv"
            / "template-4.html"
        )
        css = template_path.read_text()

        dots_rule_start = css.index(".dots i {")
        dots_rule_end = css.index("}", dots_rule_start)
        dots_rule = css[dots_rule_start:dots_rule_end]
        assert "border-radius: 50%" in dots_rule

        blocks_rule_start = css.index(".blocks i {")
        blocks_rule_end = css.index("}", blocks_rule_start)
        blocks_rule = css[blocks_rule_start:blocks_rule_end]
        assert "border-radius: 50%" not in blocks_rule

    def test_berufsbezeichnung_renders_beneath_the_centered_name(self, mocker):
        """KTD7/Plan-Annahme: Berufsbezeichnung rendert in allen neuen
        Vorlagen konsistent unter dem Namen - hier zusätzlich im zentrierten
        Kopfblock der Hauptspalte (nicht in der Sidebar)."""
        content = _full_content()
        content["berufsbezeichnung"] = "Full-Stack Developer"

        rendered = _rendered_html(mocker, template_id="template-4", **content)

        assert '<div class="header-band__name">Max Mustermann</div>' in rendered
        assert "Full-Stack Developer" in rendered
        name_pos = rendered.index('<div class="header-band__name">')
        title_pos = rendered.index('<div class="header-band__title">')
        assert name_pos < title_pos

    def test_no_photo_preview_shows_placeholder_with_photo_present_omits_it(self, mocker):
        content = _full_content()
        content["skills"] = []

        rendered_no_photo_preview = _rendered_html(
            mocker, template_id="template-4", preview=True, **_empty_content()
        )
        assert 'class="photo photo--placeholder"' in rendered_no_photo_preview

        rendered_export_no_photo = _rendered_html(
            mocker, template_id="template-4", preview=False, **content
        )
        assert "<img" not in rendered_export_no_photo


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
