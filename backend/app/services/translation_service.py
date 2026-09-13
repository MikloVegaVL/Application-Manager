"""Service zur KI-gestützten Übersetzung von Prosa-Feldern (U1, R5-R7).

Übersetzt eine Zuordnung von Feldnamen auf Fließtext über den bestehenden
lokalen Ollama-Client (`app.services.llm_client`) von Deutsch nach Englisch
oder umgekehrt. Bewusst KEIN externer Übersetzungsdienst und bewusst nur
`de`<->`en` (Scope-Grenze des Plans
`docs/plans/2026-09-13-003-feat-global-language-unification-plan.md`).

Anders als `ai_generator.py`/`pdf_parser.py` ist das Ergebnis pro Feld
fehlertolerant: Ein einzelnes Feld, dessen Übersetzung fehlschlägt, landet in
`errors` statt die gesamte Anfrage scheitern zu lassen - der Aufrufer behält
für dieses Feld seinen Originaltext (R9, "content is never lost").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.schemas.master_profile import DocumentLanguage
from app.services import llm_client
from app.services.llm_client import LlmUnavailableError, LlmValidationError

logger = logging.getLogger(__name__)

# Nur Deutsch und Englisch werden unterstützt - jede andere Kombination ist
# ein Programmierfehler, kein Nutzerfehler (die API validiert beide Sprachen
# bereits über `DocumentLanguage`).
_SUPPORTED_PAIRS: set[tuple[DocumentLanguage, DocumentLanguage]] = {("de", "en"), ("en", "de")}

# Anzeigename der Zielsprache im Prompt - bewusst ausgeschrieben, damit das
# LLM die Sprache eindeutig erkennt.
_LANGUAGE_NAMES: dict[DocumentLanguage, str] = {"de": "German", "en": "English"}


class _TranslatedText(BaseModel):
    """Struktur der schema-eingeschränkten KI-Antwort für ein einzelnes Feld
    (siehe `llm_client.generate_structured`)."""

    translation: str


@dataclass
class TranslationResult:
    """Per-Feld-Ergebnis einer Übersetzungsanfrage (siehe `translate_fields`).

    `translations` enthält jedes erfolgreich übersetzte Feld, `errors` je
    fehlgeschlagenem Feld eine Fehlermeldung. Ein Feld kann nie in beiden
    auftauchen.
    """

    translations: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _build_system_prompt(
    source_language: DocumentLanguage, target_language: DocumentLanguage
) -> str:
    """Baut den Übersetzungs-Systemprompt für das Sprachpaar."""
    source_name = _LANGUAGE_NAMES[source_language]
    target_name = _LANGUAGE_NAMES[target_language]
    return (
        f"You are a precise translator. Translate the user's text from "
        f"{source_name} into {target_name}.\n\n"
        "Answer EXCLUSIVELY with a JSON object in exactly the following shape "
        "(no prose, no markdown, no code fences):\n\n"
        '{\n  "translation": "<the translated text>"\n}\n\n'
        "Rules:\n"
        f"- Write the translation in {target_name}.\n"
        "- Keep proper nouns (person, company and institution names, product "
        "names, URLs, email addresses) unchanged.\n"
        "- Preserve the original meaning, tone and line breaks.\n"
        "- Do not add explanations or comments."
    )


def translate_fields(
    fields: dict[str, str],
    *,
    source_language: DocumentLanguage,
    target_language: DocumentLanguage,
) -> TranslationResult:
    """Übersetzt `fields` von `source_language` nach `target_language`.

    Liefert die erfolgreich übersetzten Felder in `translations` und je
    fehlgeschlagenem Feld eine Fehlermeldung in `errors`. Ein fehlgeschlagenes
    Feld fehlt in `translations` - der Aufrufer behält dafür seinen
    Originaltext (R9). Leere/whitespace-only Werte werden unverändert
    durchgereicht, ohne einen Ollama-Aufruf auszulösen. Ist
    `source_language == target_language`, wird `fields` unverändert
    zurückgegeben.

    Wirft `ValueError` für ein nicht unterstütztes Sprachpaar - das ist ein
    Programmierfehler, kein Feldübersetzungsfehler.
    """
    result = TranslationResult()

    if source_language == target_language:
        result.translations.update(fields)
        return result

    if (source_language, target_language) not in _SUPPORTED_PAIRS:
        raise ValueError(
            f"Nicht unterstütztes Sprachpaar: {source_language} -> {target_language}."
        )

    system_prompt = _build_system_prompt(source_language, target_language)

    for name, text in fields.items():
        if not text or not text.strip():
            result.translations[name] = text
            continue

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        try:
            translated = llm_client.generate_structured(_TranslatedText, messages)
        except (LlmUnavailableError, LlmValidationError) as exc:
            logger.warning("Übersetzung des Feldes %r fehlgeschlagen: %s", name, exc)
            result.errors[name] = str(exc)
            continue

        # P2: Eine leere/whitespace-only Modellantwort ist eine fehlgeschlagene
        # Übersetzung, kein gültiges Ergebnis - sonst würde ein leerer Wert das
        # Originalfeld überschreiben. Der Aufrufer behält den Originaltext (R9).
        if not translated.translation or not translated.translation.strip():
            logger.warning("Übersetzung des Feldes %r lieferte einen leeren Text.", name)
            result.errors[name] = "Modell lieferte eine leere Übersetzung."
            continue

        result.translations[name] = translated.translation

    return result
