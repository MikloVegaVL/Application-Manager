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

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.models.application import Application
from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.models.portal_submission import PortalSubmission
from app.models.profile_attachment import ProfileAttachment
from app.services.portal_agents import base as base_module
from app.services.portal_agents import session as session_module
from app.services.portal_agents.answering import answer_freetext_question
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

# Best-effort Name-Muster für den eigentlichen Submit-Button (R11) - deckt
# gängige englische/deutsche Beschriftungen ab. Muss für v1 nicht perfekt
# sein (siehe Auftrag): findet Playwright keinen passenden Button, wirft
# `get_by_role(...).click()` selbst einen `TimeoutError`, der den Lauf über
# den generischen `unhandled_error`-Pfad in `session.py` sauber beendet.
SUBMIT_BUTTON_NAME_PATTERN = re.compile(r"submit|senden|absenden|bewerben", re.IGNORECASE)

# JS-Heuristik zur Label-Auflösung einer Freitext-`<textarea>` (R7): erst
# `aria-label`, dann ein assoziiertes `<label for=...>`, dann das nächste
# umschließende `<label>` (Wrapping-Muster `<label>Text<textarea/></label>`).
# Muss nicht perfekt sein - eine fehlende Auflösung fällt in
# `_resolve_textarea_label()` unten auf `placeholder`/`name`/einen
# generischen Platzhalter zurück statt zu scheitern.
_TEXTAREA_LABEL_JS = """
(el) => {
  const ariaLabel = el.getAttribute('aria-label');
  if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();
  if (el.id) {
    const label = el.ownerDocument.querySelector(`label[for="${el.id}"]`);
    if (label && label.textContent && label.textContent.trim()) return label.textContent.trim();
  }
  const closestLabel = el.closest('label');
  if (closestLabel && closestLabel.textContent && closestLabel.textContent.trim()) {
    return closestLabel.textContent.trim();
  }
  return null;
}
"""


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
    Warten auf ein Captcha, das vielleicht nie erscheint.

    Alle `selectors` werden als EINE CSS-Selektorliste (durch Komma
    verbunden) abgefragt - ein Roundtrip statt einem pro Selektor (diese
    Prüfung läuft vor jedem Feld/jeder Freitextfrage, s. `_pause_if_captcha_
    present`, daher summiert sich das sonst schnell)."""
    return container.locator(", ".join(selectors)).count() > 0


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


def _locate_frame(session: PortalFillSession, iframe_wait_timeout_ms: float | None):
    """Navigiert zur Formular-URL und lokalisiert das Personio-iframe (R4).
    Ausgelagert aus `run()`, damit U4s eigene Tests (Feld-Ausfüllen,
    iframe-Erkennung) diesen Schritt unabhängig von der später (U6)
    angehängten Freitext-/Pre-Submit-/Submit-Pipeline aufrufen können."""
    session.page.goto(session.application_form_url)

    frame = session.page.frame_locator(PERSONIO_IFRAME_SELECTOR)
    wait_kwargs = {} if iframe_wait_timeout_ms is None else {"timeout": iframe_wait_timeout_ms}
    try:
        frame.locator("body").wait_for(state="attached", **wait_kwargs)
    except PlaywrightTimeoutError as exc:
        session._abort("iframe_not_found")
        raise IframeNotFoundError() from exc
    return frame


def _fill_known_fields(session: PortalFillSession, frame, fields: list[PersonioField]) -> None:
    """Füllt die bekannten `fields` der Reihe nach (R3/R12) - jedes nicht
    gemappte Feld pausiert statt still übersprungen zu werden. `check_cancel()`
    läuft vor jedem Feld als Abbruch-Checkpoint (R9-Analogon aus U2)."""
    _pause_if_captcha_present(session, frame)
    for field in fields:
        session.check_cancel()
        _pause_if_captcha_present(session, frame)
        result = _fill_field(frame, field)
        if not result.matched:
            session.pause("low_confidence_field")


def _resolve_textarea_label(textarea_locator) -> str:
    """Bestes verfügbares Label für eine Freitext-`<textarea>` (R7) - siehe
    `_TEXTAREA_LABEL_JS`. Fällt auf `placeholder`/`name`/einen generischen
    Platzhalter zurück, wenn keine Label-Assoziation gefunden wird (muss laut
    Auftrag nicht perfekt sein)."""
    js_label = textarea_locator.evaluate(_TEXTAREA_LABEL_JS)
    if js_label:
        return js_label
    placeholder = textarea_locator.get_attribute("placeholder")
    if placeholder:
        return placeholder
    name = textarea_locator.get_attribute("name")
    if name:
        return name
    return "Freitextfrage"


def _load_answering_context(
    application_id: int,
) -> tuple[MasterProfile | None, JobOffer | None, str | None]:
    """Lädt Profil/Stellenangebot/bereits generiertes Anschreiben frisch über
    eine KURZLEBIGE `SessionLocal()`-Session (nicht über eine bereits offene
    Session hinweg gehalten) - vermeidet, eine DB-Session über einen ggf.
    stundenlangen `session.pause()`-Wait offen zu halten (Ressourcen-Leck-
    Risiko). `MasterProfile` wird wie im Rest der App per `.first()` als das
    eine Profil dieser Single-User-Anwendung geladen (siehe `send_application`)."""
    with session_module._db_session() as db:
        application = db.get(Application, application_id)
        job_offer = db.get(JobOffer, application.job_offer_id) if application is not None else None
        profile = db.query(MasterProfile).first()
        cover_letter_text = application.cover_letter_text if application is not None else None
        return profile, job_offer, cover_letter_text


def _fill_freetext_questions(session: PortalFillSession, frame) -> None:
    """Entdeckt Freitext-Fragen (R7): jede `<textarea>` im Personio-iframe,
    die noch KEINEN Wert trägt (nicht bereits durch ein bekanntes Feld
    gefüllt), gilt als offene Frage. Scheitert `answer_freetext_question()`
    (LLM-Fehler), wird NUR dieses Feld als UNMAPPED behandelt (R12: Pause statt
    den ganzen Lauf als `unhandled_error` abzubrechen)."""
    profile, job_offer, cover_letter_text = _load_answering_context(session.application_id)
    for textarea in frame.locator("textarea").all():
        session.check_cancel()
        _pause_if_captcha_present(session, frame)
        if (textarea.input_value() or "").strip():
            continue  # bereits durch ein bekanntes Feld gefüllt
        question = _resolve_textarea_label(textarea)
        try:
            answer = answer_freetext_question(
                question=question,
                profile=profile,
                job_offer=job_offer,
                cover_letter_text=cover_letter_text,
            )
        except Exception:  # noqa: BLE001 - LLM-Fehler betrifft nur DIESES Feld (R12)
            session.pause("low_confidence_field")
            continue
        textarea.fill(answer)


def _click_submit_button(frame) -> None:
    """Klickt den Submit-Button (R11) - best-effort Name-Heuristik, siehe
    `SUBMIT_BUTTON_NAME_PATTERN`. Findet Playwright keinen Treffer, wirft
    `get_by_role(...).click()` selbst (`TimeoutError`), was den Lauf über den
    generischen `unhandled_error`-Pfad in `session.py` sauber beendet."""
    frame.get_by_role("button", name=SUBMIT_BUTTON_NAME_PATTERN).first.click()


def _record_submission(session: PortalFillSession) -> None:
    """Protokolliert einen erfolgreichen Submit (R11/R13, U1): erzeugt EINEN
    `PortalSubmission`-Datensatz (Snapshot aus dem `JobOffer`) UND setzt
    `Application.automation_state="submitted"` in einem Commit - mirrort
    `send_application`s Erfolgs-Only-Logging-Muster. Nutzt eine frische,
    KURZLEBIGE `SessionLocal()`-Session statt eine über den vorherigen
    `pre_submit_confirmation`-Pause-Wait offen gehaltene."""
    with session_module._db_session() as db:
        application = db.get(Application, session.application_id)
        job_offer = (
            db.get(JobOffer, application.job_offer_id) if application is not None else None
        )
        db.add(
            PortalSubmission(
                application_id=session.application_id,
                portal_url=session.application_form_url,
                platform="personio",
                company=job_offer.company if job_offer is not None else None,
                job_title=job_offer.title if job_offer is not None else None,
                submitted_at=datetime.now(timezone.utc),
            )
        )
        if application is not None:
            application.automation_state = "submitted"
            application.action_needed_reason = None
        db.commit()


def run(
    session: PortalFillSession,
    fields: list[PersonioField],
    *,
    iframe_wait_timeout_ms: float | None = DEFAULT_IFRAME_WAIT_TIMEOUT_MS,
) -> None:
    """Der eigentliche Personio-Lauf (R3/R4/R7/R10/R11/R12). Navigiert zur
    Formular-URL, lokalisiert das Personio-iframe, prüft/pausiert bei
    Captchas, füllt die bekannten `fields` UND entdeckte Freitext-Fragen,
    pausiert IMMER vor dem Submit (`pre_submit_confirmation`, R11 - nicht
    konditional) und klickt nach dem Resume den Submit-Button, bevor der
    Submit protokolliert wird (`PortalSubmission` + `automation_state=
    "submitted"`)."""
    frame = _locate_frame(session, iframe_wait_timeout_ms)
    _fill_known_fields(session, frame, fields)
    _fill_freetext_questions(session, frame)

    session.pause("pre_submit_confirmation")

    _click_submit_button(frame)
    _record_submission(session)
    session.close()


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
