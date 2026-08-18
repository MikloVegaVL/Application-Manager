"""Gemeinsamer Ollama-Aufruf-Helfer für schema-eingeschränkte KI-Antworten.

Bündelt an einer Stelle, was sowohl `pdf_parser.py` als auch
`ai_generator.py` brauchen:

1. Client-Konstruktion (`ollama.Client`).
2. Den schema-eingeschränkten Chat-Aufruf (`format=<JSON-Schema>`) samt
   Validierung der Antwort gegen das übergebene Pydantic-Modell.
3. Eine Retry-Schleife: Bei einem Validierungsfehler wird die ungültige
   Antwort samt dem konkreten Validierungsfehler in den Prompt aufgenommen
   und einmal erneut versucht.
4. Einen Fallback für Ollamas bekannten `$defs`/`$ref`-Bug bei verschachtelten
   Listen-Feldern (ollama/ollama#8444): Schlägt der Retry erneut auf
   demselben verschachtelten Listenfeld fehl ("strukturelles" Signal), wird
   ein letzter Versuch gegen ein abgeflachtes Schema unternommen, dessen
   Ergebnis anschließend in die ursprüngliche verschachtelte Form
   zurückgebaut wird.

Die hier definierten Fehler (`LlmUnavailableError`, `LlmValidationError`)
sind ausschließlich helferintern sichtbar - Aufrufer (`pdf_parser.py`,
`ai_generator.py`) fangen sie ab und werfen ihren eigenen, bereits
bestehenden Fehlertyp.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, TypeVar, get_args, get_origin

import httpx
import ollama
from pydantic import BaseModel, ValidationError, create_model

from app.core.config import settings

logger = logging.getLogger(__name__)

Message = dict[str, str]
ModelT = TypeVar("ModelT", bound=BaseModel)

# Interne Buchhaltung für den Abflach-Fallback: Für ein verschachteltes
# Listenfeld (`name -> Item-Modelklasse`) sowie für ein verschachteltes
# Submodell-Feld (`name -> (Original-Modelklasse, dessen eigene
# Listenfelder, dessen eigene Submodell-Felder)`).
_ListFieldMap = dict[str, type[BaseModel]]
_SubmodelMap = dict[str, tuple[type[BaseModel], "_ListFieldMap", "_SubmodelMap"]]


class LlmValidationError(Exception):
    """Wird ausgelöst, wenn die KI-Antwort auch nach Retry und Fallback nicht
    dem erwarteten Schema entspricht."""


class LlmUnavailableError(Exception):
    """Wird ausgelöst, wenn Ollama nicht erreichbar ist, die Anfrage
    fehlschlägt oder das Zeitlimit überschritten wird."""


def _build_client() -> ollama.Client:
    return ollama.Client(host=settings.OLLAMA_BASE_URL, timeout=settings.OLLAMA_TIMEOUT_SECONDS)


@lru_cache(maxsize=None)
def _schema_for(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Cached JSON-Schema für `model_cls`. Wird pro Aufruf von
    `generate_structured` mehrfach gebraucht (Erstversuch, Retry, ggf.
    Fallback-Schema) und ist für eine gegebene Modelklasse immer identisch -
    Neuberechnung bei jedem Request lohnt sich nicht."""
    return model_cls.model_json_schema()


def _call_chat(
    client: ollama.Client,
    model: str,
    messages: list[Message],
    format_schema: dict[str, Any],
) -> str:
    """Führt den eigentlichen Ollama-Chat-Aufruf aus und liefert den rohen
    Antwort-Text.

    Fängt genau die drei relevanten Fehlerarten ab - `ollama.ResponseError`,
    das eingebaute `ConnectionError` (in das Ollamas Client
    `httpx.ConnectError` unverpackt umwandelt) sowie `httpx.TimeoutException`
    (von Ollamas Client NICHT abgefangen, muss separat behandelt werden) -
    und wirft dafür einheitlich `LlmUnavailableError`, ohne erneuten Versuch
    (Retry gilt nur für Validierungsfehler, nicht für Nichterreichbarkeit).
    """
    try:
        response = client.chat(model=model, format=format_schema, messages=messages)
    except ollama.ResponseError as exc:
        logger.exception("Ollama-Aufruf fehlgeschlagen (ResponseError).")
        raise LlmUnavailableError(f"Ollama-Anfrage fehlgeschlagen: {exc}") from exc
    except ConnectionError as exc:
        logger.exception("Ollama ist nicht erreichbar.")
        raise LlmUnavailableError(f"Ollama ist nicht erreichbar: {exc}") from exc
    except httpx.TimeoutException as exc:
        logger.exception("Ollama-Aufruf hat das Zeitlimit überschritten.")
        raise LlmUnavailableError(f"Ollama-Anfrage hat das Zeitlimit überschritten: {exc}") from exc

    content = response.message.content if response and response.message else None
    if not content:
        raise LlmValidationError("Die Ollama-Antwort enthielt keine Daten.")
    return content


def _is_nested_list_field(annotation: Any) -> type[BaseModel] | None:
    """Liefert die Item-Modelklasse, falls `annotation` `list[SomeModel]`
    ist (SomeModel ein Pydantic-Modell), sonst `None`."""
    if get_origin(annotation) is not list:
        return None
    args = get_args(annotation)
    if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return args[0]
    return None


def _nested_list_field_paths(
    model_cls: type[BaseModel], prefix: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    """Ermittelt rekursiv alle Feldpfade in `model_cls`, deren Typ eine Liste
    von Pydantic-Modellen ist (direkt oder über ein verschachteltes
    Submodell-Feld erreichbar) - das ist genau die Feldklasse, die vom
    Ollama-`$defs`-Bug betroffen sein kann."""
    paths: set[tuple[str, ...]] = set()
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        if _is_nested_list_field(annotation) is not None:
            paths.add(prefix + (name,))
            continue
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths |= _nested_list_field_paths(annotation, prefix + (name,))
    return paths


def _is_structural_failure(
    first_exc: ValidationError, second_exc: ValidationError, model_cls: type[BaseModel]
) -> bool:
    """Das "strukturelle Signal": Der Retry (der den ersten Validierungsfehler
    bereits im Prompt enthielt) scheitert erneut am selben verschachtelten
    Listenfeld wie der Erstversuch - z. B. `experiences`/`education` oder
    deren Äquivalent im CV-Content-Schema. Ein Fehler auf einem anderen oder
    einem Top-Level-Feld beim zweiten Versuch ist KEIN strukturelles Signal,
    sondern gewöhnliche Retry-Erschöpfung."""
    list_paths = _nested_list_field_paths(model_cls)
    if not list_paths:
        return False

    def _hit_paths(exc: ValidationError) -> set[tuple[str, ...]]:
        hits: set[tuple[str, ...]] = set()
        for error in exc.errors():
            loc = tuple(error["loc"])
            for path in list_paths:
                if loc[: len(path)] == path:
                    hits.add(path)
        return hits

    return bool(_hit_paths(first_exc) & _hit_paths(second_exc))


@lru_cache(maxsize=None)
def _build_flat_variant(
    model_cls: type[BaseModel],
) -> tuple[type[BaseModel], _ListFieldMap, _SubmodelMap]:
    """Baut eine abgeflachte Variante von `model_cls`: Felder vom Typ
    `list[SomeModel]` werden durch ein einfaches `str`-Feld ersetzt (die
    Liste wird als JSON-kodierter String erwartet), verschachtelte
    Submodell-Felder werden rekursiv ebenfalls abgeflacht. Dadurch enthält
    das resultierende JSON-Schema keine Array-von-Objekt-Konstruktion mehr,
    die von Ollamas `$defs`/`$ref`-Bug betroffen sein könnte.

    Liefert `(abgeflachte Modelklasse, Listenfeld-Map, Submodell-Map)` -
    beide Maps werden von `_reconstruct()` gebraucht, um das Ergebnis wieder
    in die ursprüngliche verschachtelte Form zurückzubauen. Ist für eine
    gegebene `model_cls` immer identisch, daher gecacht.
    """
    list_fields: _ListFieldMap = {}
    submodels: _SubmodelMap = {}
    field_defs: dict[str, Any] = {}

    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        item_cls = _is_nested_list_field(annotation)
        if item_cls is not None:
            list_fields[name] = item_cls
            field_defs[name] = (str, "[]")
            continue
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            flat_sub, sub_list_fields, sub_submodels = _build_flat_variant(annotation)
            submodels[name] = (annotation, sub_list_fields, sub_submodels)
            default = ... if field.is_required() else field.default
            field_defs[name] = (flat_sub, default)
            continue
        # Unveränderte Felder: Original-FieldInfo wiederverwenden, damit
        # Default/Default-Factory/Constraints erhalten bleiben.
        field_defs[name] = (annotation, field)

    flat_cls = create_model(f"Flat{model_cls.__name__}", **field_defs)
    return flat_cls, list_fields, submodels


def _reconstruct(
    flat_instance: BaseModel,
    model_cls: type[BaseModel],
    list_fields: _ListFieldMap,
    submodels: _SubmodelMap,
) -> BaseModel:
    """Baut aus einer validierten Instanz der abgeflachten Modelklasse die
    ursprüngliche, verschachtelte `model_cls`-Instanz zusammen."""
    data: dict[str, Any] = {}
    for name in model_cls.model_fields:
        if name in list_fields:
            raw = getattr(flat_instance, name)
            try:
                items = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                items = []
            data[name] = items if isinstance(items, list) else []
        elif name in submodels:
            orig_sub, sub_list_fields, sub_submodels = submodels[name]
            data[name] = _reconstruct(getattr(flat_instance, name), orig_sub, sub_list_fields, sub_submodels)
        else:
            data[name] = getattr(flat_instance, name)
    return model_cls.model_validate(data)


def _retry_messages(base_messages: list[Message], invalid_content: str, error: ValidationError) -> list[Message]:
    """Baut den Retry-Prompt - die ungültige Antwort plus der konkrete
    Validierungsfehler werden angehängt, statt identisch erneut zu senden."""
    return base_messages + [
        {"role": "assistant", "content": invalid_content},
        {
            "role": "user",
            "content": (
                "Die vorherige Antwort entsprach nicht dem geforderten JSON-Schema. "
                f"Validierungsfehler:\n{error}\n\n"
                "Bitte antworte erneut - korrigiert und exakt im geforderten Format."
            ),
        },
    ]


def _fallback_messages(base_messages: list[Message]) -> list[Message]:
    """Fallback-Prompt: weist auf das abgeflachte Ersatzschema hin, in dem
    Listenfelder als JSON-kodierte Strings statt als Arrays erwartet
    werden."""
    return base_messages + [
        {
            "role": "user",
            "content": (
                "Die bisherigen Antworten entsprachen wiederholt nicht dem Schema. "
                "Antworte diesmal exakt im folgenden (abgeflachten) Format: Felder, "
                "die zuvor Listen von Objekten waren, sind jetzt als einzelner "
                "String zu befüllen, der die Liste als JSON kodiert."
            ),
        },
    ]


def generate_structured(
    model_cls: type[ModelT],
    messages: list[Message],
    *,
    model: str | None = None,
) -> ModelT:
    """Führt einen schema-eingeschränkten Ollama-Chat-Aufruf aus und liefert
    das Ergebnis als validierte Instanz von `model_cls`.

    Ablauf:

    1. Erstversuch gegen `model_cls`s JSON-Schema.
    2. Bei Validierungsfehler: ein Retry, dessen Prompt die ungültige
       Antwort und den konkreten Validierungsfehler enthält.
    3. Scheitert auch der Retry, und betrifft der Fehler in beiden
       Versuchen dasselbe verschachtelte Listenfeld (das "strukturelle"
       Signal, siehe `_is_structural_failure`), ein letzter Versuch gegen
       ein abgeflachtes Schema, dessen Ergebnis in die ursprüngliche
       verschachtelte Form zurückgebaut wird.
    4. Andernfalls (kein strukturelles Signal) wird nach dem Retry
       aufgegeben.

    Wirft `LlmUnavailableError`, wenn Ollama nicht erreichbar ist, die
    Anfrage fehlschlägt oder das Zeitlimit überschritten wird (kein Retry in
    diesem Fall). Wirft `LlmValidationError`, wenn auch nach Retry/Fallback
    keine gültige Antwort zustande kam. Beide Fehler sind helferintern -
    Aufrufer übersetzen sie in ihren eigenen bestehenden Fehlertyp.
    """
    resolved_model = model or settings.OLLAMA_MODEL
    schema = _schema_for(model_cls)

    with _build_client() as client:
        content = _call_chat(client, resolved_model, messages, schema)
        try:
            return model_cls.model_validate_json(content)
        except ValidationError as exc:
            # Python löscht die `as`-Bindung eines except-Blocks bei dessen
            # Verlassen - daher hier explizit in eine normale Variable sichern.
            first_exc = exc
            logger.warning("Ollama-Antwort entsprach nicht dem Schema (Versuch 1): %s", first_exc)

        retry_messages = _retry_messages(messages, content, first_exc)
        content = _call_chat(client, resolved_model, retry_messages, schema)
        try:
            return model_cls.model_validate_json(content)
        except ValidationError as exc:
            second_exc = exc
            logger.warning("Ollama-Antwort entsprach nicht dem Schema (Versuch 2): %s", second_exc)

        if not _is_structural_failure(first_exc, second_exc, model_cls):
            raise LlmValidationError(
                "Die Ollama-Antwort entsprach auch nach einem Retry nicht dem erwarteten Schema."
            ) from second_exc

        logger.warning(
            "Wiederholter Validierungsfehler auf demselben verschachtelten Feld - "
            "versuche Fallback auf abgeflachtes Schema."
        )
        flat_cls, list_fields, submodels = _build_flat_variant(model_cls)
        flat_schema = _schema_for(flat_cls)
        fallback_messages = _fallback_messages(messages)
        content = _call_chat(client, resolved_model, fallback_messages, flat_schema)
        try:
            flat_instance = flat_cls.model_validate_json(content)
        except ValidationError as fallback_exc:
            logger.warning("Auch das abgeflachte Fallback-Schema wurde nicht erfüllt: %s", fallback_exc)
            raise LlmValidationError(
                "Die Ollama-Antwort entsprach auch im Fallback-Schema nicht dem erwarteten Format."
            ) from fallback_exc

        try:
            return _reconstruct(flat_instance, model_cls, list_fields, submodels)
        except ValidationError as reconstruct_exc:
            logger.warning("Rekonstruktion aus dem abgeflachten Fallback fehlgeschlagen: %s", reconstruct_exc)
            raise LlmValidationError(
                "Die rekonstruierte Ollama-Antwort entsprach nicht dem erwarteten Schema."
            ) from reconstruct_exc
