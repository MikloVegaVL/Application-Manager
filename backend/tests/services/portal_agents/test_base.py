"""Tests für die generische Feld-Erkennung/Fuzzy-Matching-Basis (U3).

Deckt die U3-Testszenarien des Plans ab:
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md

Playwright-Tests laufen gegen einen echten (headless) Chromium via
`page.set_content(...)` - kein Netzwerk, keine Fixtures nötig (siehe
Moduldoc von `tests/services/job_sources/test_shared.py` für das übliche
Playwright-Testmuster in diesem Repo; dort wird `sync_playwright` gemockt,
hier reicht ein echter, kurzlebiger Browser, weil wir tatsächliches
DOM-Verhalten - Label-Assoziation, `<select>`-Optionen, Datei-Inputs -
prüfen wollen statt nur den Aufrufcode selbst)."""
from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from app.models.profile_attachment import ProfileAttachment
from app.services.portal_agents import base as base_module


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    yield page
    page.close()


# --- Textfeld: Lokalisierung + Ausfüllen ----------------------------------


def test_fill_text_field_locates_labeled_input_and_fills_it(page):
    """Happy path: ein gelabeltes Textfeld wird gefunden und ausgefüllt."""
    page.set_content('<label>Full Name<input type="text" /></label>')

    result = base_module.fill_text_field(page, "Max Mustermann", label="Full Name")

    assert result.matched is True
    assert result.value == "Max Mustermann"
    assert page.get_by_label("Full Name").input_value() == "Max Mustermann"


def test_fill_text_field_reports_unmapped_when_field_not_found(page):
    """R12: kein passendes Feld -> UNMAPPED statt Exception."""
    page.set_content("<div>Kein Formular hier.</div>")

    result = base_module.fill_text_field(page, "irrelevant", label="Nicht vorhanden")

    assert result.matched is False
    assert result.reason == base_module.FIELD_NOT_FOUND


# --- Dropdown-Fuzzy-Matching (R5) -----------------------------------------

SELECT_HTML = """
<label>Country
  <select>
    <option value="">Bitte wählen</option>
    <option value="DE">Germany</option>
    <option value="FR">France</option>
  </select>
</label>
"""


def test_select_dropdown_option_matches_fuzzy_profile_value(page):
    """Happy path: "Deutschland" matcht (über den Value-Code "DE", nicht
    das Label "Germany") und die richtige Option wird ausgewählt."""
    page.set_content(SELECT_HTML)

    result = base_module.select_dropdown_option(page, "Deutschland", label="Country")

    assert result.matched is True
    assert result.value == "DE"
    assert page.get_by_label("Country").input_value() == "DE"


def test_select_dropdown_option_unmapped_when_no_close_match(page):
    """Edge: kein naher Treffer ("Narnia") -> UNMAPPED statt Force-Pick."""
    page.set_content(SELECT_HTML)

    result = base_module.select_dropdown_option(page, "Narnia", label="Country")

    assert result.matched is False
    assert result.reason == base_module.NO_MATCHING_OPTION
    # Kein Seiteneffekt: die Auswahl bleibt beim initialen leeren Wert.
    assert page.get_by_label("Country").input_value() == ""


# --- best_fuzzy_match_index(): reine Logik, kein Playwright --------------


def test_best_fuzzy_match_index_is_case_insensitive():
    labels = ["Germany", "France"]
    values = ["DE", "FR"]

    assert base_module.best_fuzzy_match_index("GERMANY", labels, values) == 0


def test_best_fuzzy_match_index_is_diacritic_insensitive():
    labels = ["Über uns", "Kontakt"]
    values = ["about", "contact"]

    assert base_module.best_fuzzy_match_index("uber uns", labels, values) == 0


def test_best_fuzzy_match_index_returns_none_below_threshold():
    labels = ["Germany", "France"]
    values = ["DE", "FR"]

    assert base_module.best_fuzzy_match_index("Narnia", labels, values) is None


# --- Datei-Upload (R6) ------------------------------------------------------


def test_upload_attachment_file_sets_input_files_when_path_exists(page, tmp_path):
    """Happy path: eine existierende Anhang-Datei wird an das Datei-Input
    gehängt."""
    page.set_content('<label>Lebenslauf<input type="file" /></label>')
    file_path = tmp_path / "cv.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")
    attachment = ProfileAttachment(file_path=str(file_path), filename="cv.pdf")

    result = base_module.upload_attachment_file(page, attachment, label="Lebenslauf")

    assert result.matched is True
    # Browser liefern aus Sicherheitsgründen nur einen Fake-Pfad zurück,
    # der aber den Dateinamen enthält - genug, um den Upload zu verifizieren.
    assert "cv.pdf" in page.get_by_label("Lebenslauf").input_value()


def test_upload_attachment_file_reports_unmapped_when_path_missing(page, tmp_path):
    """Error path: `file_path` existiert nicht -> UNMAPPED statt Exception
    aus `set_input_files` (R12)."""
    page.set_content('<label>Lebenslauf<input type="file" /></label>')
    missing_path = tmp_path / "does-not-exist.pdf"
    attachment = ProfileAttachment(file_path=str(missing_path), filename="cv.pdf")

    result = base_module.upload_attachment_file(page, attachment, label="Lebenslauf")

    assert result.matched is False
    assert result.reason == base_module.FILE_NOT_FOUND
