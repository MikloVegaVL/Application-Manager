"""Plattformunabhängige Basisschicht für den Portal-Auto-Fill-Agenten (U3).

Identifiziert und füllt Standard-Formularfelder (Text, E-Mail, Telefon,
Datei-Upload, Select) und matcht Profilwerte fuzzy gegen Dropdown-Optionen
(R3, R5, R6, R12). Enthält KEINE Personio-spezifische Logik - das ist U4
(späterer Aufrufer dieses Moduls). Siehe
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md.

Feldsuche (R3) ist accessible-first: `get_by_label` (deckt `<label>`-Text,
`aria-label` UND `aria-labelledby` ab) vor `get_by_placeholder`, erst danach
Attribut-Selektoren (`autocomplete`/`name`/`type`) als Fallback für Felder
ohne zugängliches Label. `locate_field()`/die Fill-Funktionen nehmen dafür
absichtlich ein generisches `container`-Objekt entgegen (Playwright `Page`
ODER `FrameLocator` - beide haben identische `get_by_label`/`get_by_
placeholder`/`locator`-Methoden), NIE konkret `Page` - eine spätere Unit
(U4) reicht hier einen frame-gebundenen `FrameLocator` für Personios iframe
durch.

Vertragspunkt für Aufrufer (R12): jede Fill-/Match-Funktion liefert ein
`FieldFillResult` zurück statt eine Exception zu werfen. `matched=False`
bedeutet, das Feld muss sichtbar als "Action needed"/UNMAPPED markiert
werden - NIE stillschweigend übersprungen oder auf einen unsicheren
Kandidaten geraten (siehe `best_fuzzy_match_index()`: liefert `None` statt
den nächstbesten Treffer unterhalb `DEFAULT_MATCH_THRESHOLD` zu erzwingen).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process, utils

from app.models.profile_attachment import ProfileAttachment

# `reason`-Werte auf `FieldFillResult` bei `matched=False` - als Konstanten
# statt Freitext, damit Aufrufer (U4) sie ohne Stringvergleich-Rätselraten
# unterscheiden können.
FIELD_NOT_FOUND = "field_not_found"
NO_MATCHING_OPTION = "no_matching_option"
FILE_NOT_FOUND = "file_not_found"

# Ab welchem rapidfuzz-Score (0-100) eine Dropdown-Option als sicher genug
# gilt, um automatisch ausgewählt zu werden (R5/R12) - siehe `best_fuzzy_
# match_index()`. Ein fester Wert, testempirisch gewählt (siehe Moduldoc der
# Tests): trennt "Deutschland" -> "DE" (Score 90) sauber von "Narnia" ohne
# passende Option (Score 45).
DEFAULT_MATCH_THRESHOLD = 80.0


@dataclass
class FieldFillResult:
    """Ergebnis EINES Fill-/Match-Versuchs für ein einzelnes Formularfeld."""

    matched: bool
    field_label: str
    value: str | None = None
    reason: str | None = None


# --- Feldsuche -----------------------------------------------------------


def locate_field(
    container,
    *,
    label: str | None = None,
    placeholder: str | None = None,
    name: str | None = None,
    input_type: str | None = None,
    autocomplete: str | None = None,
):
    """Sucht EIN Formularfeld in `container` (Playwright `Page` oder
    `FrameLocator`), accessible-first (R3). Liefert `None`, wenn nichts
    gefunden wurde - wirft NIE, Aufrufer melden das Feld dann als UNMAPPED
    (R12)."""
    if label:
        candidate = container.get_by_label(label)
        if candidate.count() > 0:
            return candidate.first
    if placeholder:
        candidate = container.get_by_placeholder(placeholder)
        if candidate.count() > 0:
            return candidate.first
    # Kein zugängliches Label/Placeholder vorhanden - Attribut-Selektoren
    # als Fallback, in absteigender Spezifität.
    for attr, value in (("autocomplete", autocomplete), ("name", name), ("type", input_type)):
        if value:
            candidate = container.locator(f'[{attr}="{value}"]')
            if candidate.count() > 0:
                return candidate.first
    return None


def _field_label(label: str | None, placeholder: str | None, name: str | None, *rest: str | None) -> str:
    """Bester verfügbarer Anzeigename für ein Feld in `FieldFillResult` -
    nur für Reporting/Logging relevant, keine funktionale Bedeutung."""
    for candidate in (label, placeholder, name, *rest):
        if candidate:
            return candidate
    return "?"


# --- Text-/E-Mail-/Tel-Felder --------------------------------------------


def fill_text_field(
    container,
    value: str,
    *,
    label: str | None = None,
    placeholder: str | None = None,
    name: str | None = None,
    input_type: str | None = None,
    autocomplete: str | None = None,
) -> FieldFillResult:
    """Füllt ein Text-artiges Feld (Text/E-Mail/Tel) mit `value` (R3)."""
    field_label = _field_label(label, placeholder, name, input_type, autocomplete)
    locator = locate_field(
        container,
        label=label,
        placeholder=placeholder,
        name=name,
        input_type=input_type,
        autocomplete=autocomplete,
    )
    if locator is None:
        return FieldFillResult(matched=False, field_label=field_label, reason=FIELD_NOT_FOUND)
    locator.fill(value)
    return FieldFillResult(matched=True, field_label=field_label, value=value)


# --- Dropdown-Fuzzy-Matching (R5) ----------------------------------------


def _normalize_for_matching(text: str) -> str:
    """Normalisiert Text vor dem Fuzzy-Vergleich: NFKD-Zerlegung + Entfernen
    kombinierender Zeichen (Akzente, z. B. "Ü" -> "U") ZUSÄTZLICH zu
    rapidfuzz's eingebauter `default_process` (Kleinschreibung, Whitespace-
    Normalisierung) - `default_process` allein entfernt keine Diakritika."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return utils.default_process(without_marks)


def best_fuzzy_match_index(
    profile_value: str,
    option_labels: list[str],
    option_values: list[str],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> int | None:
    """Matcht `profile_value` gegen `option_labels` UND `option_values`
    (Index-parallel, z. B. Label "Germany" mit Value "DE") und liefert den
    Index der besten Option - oder `None`, wenn der beste Score unter
    `threshold` liegt (R12: kein Force-Pick des nächstbesten Kandidaten).

    Genommen wird pro Option das Maximum aus Label- und Value-Score (ein
    `<select>` nutzt ggf. einen ISO-/internen Code als `value`, z. B.
    value="DE", während das Label "Germany" anzeigt - "Deutschland" matcht
    dann kaum gegen das Label, aber stark gegen den Value-Code)."""
    if not option_labels:
        return None
    label_match = process.extractOne(
        profile_value, option_labels, scorer=fuzz.WRatio, processor=_normalize_for_matching
    )
    value_match = process.extractOne(
        profile_value, option_values, scorer=fuzz.WRatio, processor=_normalize_for_matching
    )
    candidates = [match for match in (label_match, value_match) if match is not None]
    if not candidates:
        return None
    _, best_score, best_index = max(candidates, key=lambda match: match[1])
    if best_score < threshold:
        return None
    return best_index


def select_dropdown_option(
    container,
    profile_value: str,
    *,
    label: str | None = None,
    placeholder: str | None = None,
    name: str | None = None,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> FieldFillResult:
    """Lokalisiert ein `<select>`-Feld und wählt die per `best_fuzzy_match_
    index()` beste Option für `profile_value` (R5)."""
    field_label = _field_label(label, placeholder, name)
    locator = locate_field(container, label=label, placeholder=placeholder, name=name)
    if locator is None:
        return FieldFillResult(matched=False, field_label=field_label, reason=FIELD_NOT_FOUND)

    options = locator.locator("option").all()
    option_labels = [option.inner_text().strip() for option in options]
    # Fehlt das `value`-Attribut im Markup, fällt der Browser auf den
    # Textinhalt zurück (HTML-Spezifikation) - dasselbe hier nachbilden,
    # damit `select_option(value=...)` unten immer den korrekten Wert trifft.
    option_values = [
        (option.get_attribute("value") or option_labels[i]) for i, option in enumerate(options)
    ]

    best_index = best_fuzzy_match_index(profile_value, option_labels, option_values, threshold=threshold)
    if best_index is None:
        return FieldFillResult(matched=False, field_label=field_label, reason=NO_MATCHING_OPTION)

    chosen_value = option_values[best_index]
    locator.select_option(value=chosen_value)
    return FieldFillResult(matched=True, field_label=field_label, value=chosen_value)


# --- Datei-Upload (R6) -----------------------------------------------------


def upload_attachment_file(
    container,
    attachment: ProfileAttachment,
    *,
    label: str | None = None,
    placeholder: str | None = None,
    name: str | None = None,
) -> FieldFillResult:
    """Hängt `attachment` an ein Datei-Upload-Feld (R6). Prüft die Existenz
    der Datei auf der Festplatte ZUERST (gleiches Muster wie
    `app.api.applications.send_application`'s Anhang-Handling) - eine
    fehlende Datei wird als UNMAPPED gemeldet (R12) statt `set_input_files`
    werfen zu lassen."""
    field_label = _field_label(label, placeholder, name, attachment.filename)
    file_path = Path(attachment.file_path)
    if not file_path.exists():
        return FieldFillResult(matched=False, field_label=field_label, reason=FILE_NOT_FOUND)

    locator = locate_field(container, label=label, placeholder=placeholder, name=name, input_type="file")
    if locator is None:
        return FieldFillResult(matched=False, field_label=field_label, reason=FIELD_NOT_FOUND)

    locator.set_input_files(str(file_path))
    return FieldFillResult(matched=True, field_label=field_label, value=attachment.filename)
