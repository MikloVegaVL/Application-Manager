"""Personio-Parser für den Portal-Auto-Fill-Agenten (U4).

Fährt Personios (typischerweise cross-origin gehostetes) Bewerbungsformular-
Embed komplett: findet dessen iframe generisch über ein Domain-Fragment-
Muster, mappt Felder über U3s plattformunabhängige Detection-/Fill-Schicht
(`app.services.portal_agents.base`) gegen einen frame-gebundenen
`FrameLocator`, erkennt Captchas (Präsenz, nie Lösen/Umgehen) und pausiert
über U2s `PortalFillSession.pause()`. Siehe
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md
(R3/R4/R10/R12, KTD4).

Bewusst dünn gehalten (Unit-Pattern-Vorgabe): komponiert nur U2s Pause-/
Cancel-Primitive und U3s Erkennung/Matching, statt beides neu zu
implementieren. Die konkrete Zuordnung "welcher Profil-/Anhang-Wert füllt
welches Feld" (R4) wird bewusst NICHT hier fest verdrahtet (z. B. per
Vorname/Nachname-Splitting von `MasterProfile.full_name`, Label-Ratespiel
für Personios tatsächliche Feldtexte) - stattdessen nimmt diese Unit eine
generische `list[PersonioField]` entgegen, die der Aufrufer (spätere
Wiring-Unit, die MasterProfile/ProfileAttachment/Application zusammenführt)
befüllt. Das hält diese Unit exakt so generisch testbar wie ihre eigenen
Testszenarien es verlangen (Fixtures aus ein paar Textfeldern, einem
`<select>`, einem Datei-Input - keine echte Personio-Formularstruktur nötig).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.models.profile_attachment import ProfileAttachment
from app.services.portal_agents import base as base_module
from app.services.portal_agents import session as session_module
from app.services.portal_agents.session import PortalFillSession

# Personios Formular-Embed generisch über ein Domain-Fragment im `src`
# erkennen (R4) - NIE eine fest kodierte Employer-Subdomain (jeder Kunde hat
# seine eigene, z. B. "acme.jobs.personio.de", "acme.jobs.personio.com").
PERSONIO_IFRAME_SELECTOR = 'iframe[src*="personio"]'

# Wie lange auf das Erscheinen des Personio-iframes gewartet wird, bevor der
# Lauf als "iframe_not_found" (KTD4) fehlschlägt. `None` = Playwrights
# eigener Default-Locator-Timeout (aktuell 30s) - siehe Moduldoc-Hinweis im
# Auftrag: "Playwright's default locator timeout ... is fine as the bound".
# Als Parameter überschreibbar, damit Tests den Fehlerfall nicht 30s lang
# abwarten müssen.
DEFAULT_IFRAME_WAIT_TIMEOUT_MS: float | None = None

# Bekannte Captcha-Präsenz-Signaturen (R10) - reCAPTCHA, hCaptcha, Cloudflare
# Turnstile. Reine Präsenzerkennung, niemals Lösen/Umgehen versuchen.
CAPTCHA_SELECTORS: tuple[str, ...] = (
    'iframe[src*="recaptcha"]',
    '.g-recaptcha[data-sitekey]',
    'iframe[src*="hcaptcha.com"]',
    '.h-captcha[data-sitekey]',
    'div[data-hcaptcha-widget-id]',
    'iframe[src*="challenges.cloudflare.com"]',
    "#challenge-stage",
    'input[name="cf-turnstile-response"]',
)


class IframeNotFoundError(session_module._StopRun):
    """Kein Personio-iframe innerhalb der Wartezeit gefunden (KTD4).

    Das ist ein TERMINALER Zustand, kein Pause-und-Weiter-Fall: ein Mensch,
    der `resume()` aufruft, kann ein fehlendes iframe nicht zum Erscheinen
    bringen. Deshalb ruft `run()` unten NICHT `session.pause()` auf, sondern
    räumt selbst genauso auf wie `PortalFillSession.pause()`/`check_cancel()`
    es bei einem terminalen Abbruch auch tun (Browser schließen, expliziten
    DB-Status setzen, Registry-Eintrag entfernen) und wirft danach diese
    Exception. Sie erbt bewusst von U2s (modul-internem) `_StopRun`, damit
    `start_session()`s generischer Except-Handler sie wie jeden anderen schon
    selbst behandelten Abbruch NUR durchreicht - und den hier bereits
    gesetzten Grund "iframe_not_found" NICHT mit "unhandled_error"
    überschreibt. Keine Änderung an `session.py` nötig: die komplette
    Bereinigung passiert hier in dieser Unit."""


@dataclass
class PersonioField:
    """Eine generische Feld-Ausfüll-Anweisung: WAS gesucht wird (Label/
    Placeholder/Name/Typ/Autocomplete, identisch zu U3s Parametern) und WOMIT
    es gefüllt werden soll. `kind` bestimmt, welche U3-Funktion aufgerufen
    wird."""

    kind: str  # "text" | "select" | "file"
    value: str | ProfileAttachment
    label: str | None = None
    placeholder: str | None = None
    name: str | None = None
    input_type: str | None = None
    autocomplete: str | None = None


def _any_selector_present(container, selectors: tuple[str, ...]) -> bool:
    """`Locator.count()` wartet NICHT (im Gegensatz zu den meisten anderen
    Playwright-Aktionen) - liefert sofort die aktuelle Trefferzahl im DOM.
    Genau das brauchen wir hier: eine reine Momentaufnahme-Prüfung, kein
    Warten auf ein Captcha, das vielleicht nie erscheint."""
    return any(container.locator(selector).count() > 0 for selector in selectors)


def captcha_present(page, frame) -> bool:
    """Prüft BEIDE Frames (Hauptseite + Personio-iframe) auf bekannte
    Captcha-Signaturen (R10) - reine Präsenzerkennung."""
    return _any_selector_present(page, CAPTCHA_SELECTORS) or _any_selector_present(
        frame, CAPTCHA_SELECTORS
    )


def _pause_if_captcha_present(session: PortalFillSession, frame) -> None:
    if captcha_present(session.page, frame):
        session.pause("captcha")


def _fill_field(frame, field: PersonioField) -> base_module.FieldFillResult:
    if field.kind == "text":
        return base_module.fill_text_field(
            frame,
            field.value,
            label=field.label,
            placeholder=field.placeholder,
            name=field.name,
            input_type=field.input_type,
            autocomplete=field.autocomplete,
        )
    if field.kind == "select":
        return base_module.select_dropdown_option(
            frame, field.value, label=field.label, placeholder=field.placeholder, name=field.name
        )
    if field.kind == "file":
        return base_module.upload_attachment_file(
            frame, field.value, label=field.label, placeholder=field.placeholder, name=field.name
        )
    raise ValueError(f"Unbekannte PersonioField.kind: {field.kind!r}")


def run(
    session: PortalFillSession,
    fields: list[PersonioField],
    *,
    iframe_wait_timeout_ms: float | None = DEFAULT_IFRAME_WAIT_TIMEOUT_MS,
) -> None:
    """Der eigentliche Personio-Lauf (R3/R4/R10/R12). Navigiert zur
    Formular-URL, lokalisiert das Personio-iframe, prüft/pausiert bei
    Captchas und füllt `fields` der Reihe nach - jedes nicht gemappte Feld
    (R12) pausiert statt still übersprungen zu werden. `check_cancel()` läuft
    vor jedem Feld als Abbruch-Checkpoint (R9-Analogon aus U2)."""
    session.page.goto(session.application_form_url)

    frame = session.page.frame_locator(PERSONIO_IFRAME_SELECTOR)
    wait_kwargs = {} if iframe_wait_timeout_ms is None else {"timeout": iframe_wait_timeout_ms}
    try:
        frame.locator("body").wait_for(state="attached", **wait_kwargs)
    except PlaywrightTimeoutError as exc:
        session.close()
        session._set_state("failed", "iframe_not_found")
        session_module._unregister(session.application_id)
        raise IframeNotFoundError() from exc

    _pause_if_captcha_present(session, frame)

    for field in fields:
        session.check_cancel()
        _pause_if_captcha_present(session, frame)
        result = _fill_field(frame, field)
        if not result.matched:
            session.pause("low_confidence_field")


def build_personio_run_fn(
    fields: list[PersonioField],
    *,
    iframe_wait_timeout_ms: float | None = DEFAULT_IFRAME_WAIT_TIMEOUT_MS,
) -> Callable[[PortalFillSession], None]:
    """Baut ein `run_fn`, kompatibel mit `session.start_session()`s Signatur
    (`Callable[[PortalFillSession], None]`)."""

    def _run(session: PortalFillSession) -> None:
        run(session, fields, iframe_wait_timeout_ms=iframe_wait_timeout_ms)

    return _run
