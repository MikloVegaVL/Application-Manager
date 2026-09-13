"""Service zur KI-gestützten Übersetzung von Prosa-Feldern (U3 des
CV-Translation-Batching-Plans:
docs/plans/2026-09-13-004-perf-cv-translation-batching-plan.md).

Übersetzt eine Zuordnung von Feldnamen auf Fließtext in EINEM
schema-eingeschränkten Ollama-Aufruf (statt einem Aufruf pro Feld) über den
bestehenden lokalen Ollama-Client (`app.services.llm_client`) von Deutsch nach
Englisch oder umgekehrt. Bewusst KEIN externer Übersetzungsdienst und bewusst
nur `de`<->`en` (Scope-Grenze des Plans
`docs/plans/2026-09-13-003-feat-global-language-unification-plan.md`).

Die Antwort ist bewusst ein flaches `{feldname: übersetzung}`-Objekt: ein
`dict[str, str]` erzeugt im JSON-Schema nur `additionalProperties` und damit
kein `$defs`/`$ref` - so wird Ollamas bekannter Bug bei verschachtelten
Listenfeldern umgangen (siehe `llm_client` sowie
docs/solutions/integration-issues/ollama-structured-output-nested-list-schema-validation-failure.md).

Fehlertoleranz pro Feld: Ein Feld, dessen Übersetzung im Ergebnis fehlt oder
leer ist, landet in `errors` - der Aufrufer behält dafür seinen Originaltext
(R4). Scheitert der gesamte Batch (Ollama nicht erreichbar oder
Schema-Verletzung), landen alle angefragten nicht-leeren Felder in `errors`;
der Aufruf selbst schlägt nicht fehl.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

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

# Explizites Kontext-/Ausgabebudget für den Batch (KTD4): der Batch ist der
# größte Prompt der App und `_call_chat` setzt sonst keine `options`. `num_ctx`
# deckt Systemprompt, realistische Feldmap und das Retry-Echo ab.
_BATCH_OPTIONS: dict[str, int] = {"num_ctx": 8192, "num_predict": 2048}


class _BatchTranslation(BaseModel):
    """Struktur der schema-eingeschränkten KI-Antwort für den gesamten
    Feld-Batch: Feldname -> übersetzter Text (siehe
    `llm_client.generate_structured`).

    `translations` ist bewusst pflichtig und zusätzliche Top-Level-Schlüssel
    sind verboten: Eine Antwort ohne den `translations`-Wrapper (z. B. die
    flache Feldmap direkt) soll die Validierung verletzen und den Retry
    auslösen, statt still als leere Map durchzugehen und alle Felder als
    Fehler zu werten."""

    model_config = ConfigDict(extra="forbid")

    translations: dict[str, str]


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
    """Baut den Übersetzungs-Systemprompt für den Feld-Batch."""
    source_name = _LANGUAGE_NAMES[source_language]
    target_name = _LANGUAGE_NAMES[target_language]
    return (
        f"You are a precise translator. Translate each field's text from "
        f"{source_name} into {target_name}.\n\n"
        "Answer EXCLUSIVELY with a JSON object in exactly the following shape "
        "(no prose, no markdown, no code fences):\n\n"
        '{\n  "translations": {\n    "<field name from the input>": "<translated text>"\n  }\n}\n\n'
        "Rules:\n"
        f"- Write every translation in {target_name}.\n"
        "- Use exactly the field names from the input JSON as keys; never "
        "rename, add, drop, or echo an example placeholder.\n"
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
    """Übersetzt `fields` von `source_language` nach `target_language` in EINEM
    Batched-Aufruf (R1).

    Liefert die erfolgreich übersetzten Felder in `translations` und je
    fehlgeschlagenem Feld eine Fehlermeldung in `errors` (R4). Leere/
    whitespace-only Werte werden unverändert durchgereicht, ohne den Batch zu
    vergrößern. Ist `source_language == target_language`, wird `fields`
    unverändert zurückgegeben. Scheitert der Batch als Ganzes, landen alle
    nicht-leeren Felder in `errors`.

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

    # Partition: leere Werte direkt durchreichen, nicht-leere in den Batch.
    batch: dict[str, str] = {}
    for name, text in fields.items():
        if not text or not text.strip():
            result.translations[name] = text
        else:
            batch[name] = text

    if not batch:
        return result

    system_prompt = _build_system_prompt(source_language, target_language)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
    ]

    try:
        response = llm_client.generate_structured(_BatchTranslation, messages, options=_BATCH_OPTIONS)
    except (LlmUnavailableError, LlmValidationError) as exc:
        logger.warning("Batch-Übersetzung fehlgeschlagen: %s", exc)
        for name in batch:
            result.errors[name] = str(exc)
        return result

    returned = response.translations
    for name in batch:
        translated = returned.get(name)
        # Eine fehlende oder leere Modellantwort ist eine fehlgeschlagene
        # Übersetzung, kein gültiges Ergebnis - sonst würde ein leerer Wert das
        # Originalfeld überschreiben. Der Aufrufer behält den Originaltext (R4).
        if not translated or not translated.strip():
            logger.warning("Übersetzung des Feldes %r fehlte oder war leer.", name)
            result.errors[name] = "Modell lieferte keine gültige Übersetzung."
            continue

        result.translations[name] = translated

    return result
