"""Sitzungsverwaltung für den Portal-Auto-Fill-Agenten (U2).

Besitzt den headed-Playwright-Browser-Lebenszyklus (Start/Pause/Resume/
Abbruch) unabhängig vom Feld-Mapping (spätere Units U3/U4). Siehe
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md.

Wichtigste Invariante (R9): Playwrights synchrones API bindet Browser/
Context/Page über seinen Greenlet-Dispatcher an genau den OS-Thread, der sie
erzeugt hat - ein Aufruf einer Playwright-Methode (z. B. `browser.close()`)
von einem ANDEREN Thread aus wirft oder hängt, statt nur subtil falsch zu
funktionieren. Deshalb gilt strikt: NUR der Thread, der `PortalFillSession.
launch()` aufgerufen hat (der in `start_session()` gestartete Hintergrund-
Thread), ruft je eine Methode auf `browser`/`page` auf. Die API-Schicht
(spätere Unit U6) sowie die Startup-/Shutdown-Hooks unten fassen den Browser
NIE direkt an - sie setzen nur Flags/Events (`cancel_requested`, das Resume-
`Event`), die der besitzende Thread selbst liest und befolgt.

Registry-Muster (`_active_sessions`/`_active_sessions_lock`) bewusst analog
zu `_generating_job_offer_ids`/`_generating_lock` in `app.api.applications`:
rein prozessweiter In-Memory-Zustand, passend zum aktuellen Single-Process-
Deployment (`uvicorn app.main:app` ohne `--workers`).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from app.db.database import SessionLocal
from app.models.application import Application


@contextmanager
def _db_session() -> Iterator[DBSession]:
    """Kurzlebige DB-Session außerhalb des Request-Zyklus (kein `get_db`-
    Dependency verfügbar, da dieser Code im Session-Hintergrund-Thread bzw.
    in Startup-/Shutdown-Hooks läuft). Gemeinsam genutzt von `_set_state`/
    `reset_stale_automation_state` hier sowie `personio.py`s
    `_load_answering_context`/`_record_submission`."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

logger = logging.getLogger(__name__)

# Modul-Level-Import statt Import innerhalb einer Methode: dadurch lässt sich
# `sync_playwright` in Tests einfach patchen (gleiches Muster wie
# `app.services.job_sources.shared`, siehe dessen Docstring/Tests).
try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - Playwright ist in requirements.txt gelistet
    sync_playwright = None  # type: ignore[assignment]

# Wie lange eine Pause (Captcha/Low-Confidence-Feld/Pre-Submit-Bestätigung,
# R10/R11) maximal auf eine Nutzeraktion (Resume) wartet, bevor der Lauf als
# "failed"/"timeout" abgebrochen wird. Aktuell ein fester Wert - könnte
# später konfigurierbar (z. B. per Setting) gemacht werden.
PAUSE_TIMEOUT_SECONDS = 3600

# Wie lange der Shutdown-Hook auf das saubere Selbst-Beenden einer noch
# laufenden Session wartet, bevor er aufgibt und nur noch loggt. Der
# Chromium-Kindprozess wird spätestens beim Prozessende vom OS beendet.
SHUTDOWN_GRACE_SECONDS = 5.0

_active_sessions: dict[int, "PortalFillSession"] = {}
_active_sessions_lock = threading.Lock()


class SessionAlreadyActiveError(Exception):
    """Für diese `application_id` läuft bereits ein Portal-Auto-Fill-Lauf.

    Vom Aufrufer (spätere API-Unit U6) auf HTTP 409 zu mappen.
    """

    def __init__(self, application_id: int) -> None:
        super().__init__(f"Für application_id={application_id} läuft bereits ein Portal-Auto-Fill-Lauf.")
        self.application_id = application_id


class _StopRun(Exception):
    """Interne Basisklasse: die Laufschleife soll sauber abbrechen, weil
    `pause()`/`check_cancel()` den Abbruch bereits vollständig behandelt
    (Browser geschlossen, DB-Status gesetzt, Registry-Eintrag entfernt)
    haben - der äußere Try/Except in `start_session()` soll das NICHT
    nochmal als "unhandled_error" behandeln."""


class PauseTimedOutError(_StopRun):
    """Eine Pause wurde nicht innerhalb von `PAUSE_TIMEOUT_SECONDS` durch
    `resume()` aufgelöst."""


class RunCancelledError(_StopRun):
    """Der Lauf wurde per `request_cancel()` abgebrochen."""


class PortalFillSession:
    """Eine einzelne Portal-Auto-Fill-Sitzung für genau eine `Application`.

    Besitzt Browser/Context/Page - ausschließlich vom Thread anzufassen, der
    `launch()` aufgerufen hat (siehe Moduldoc)."""

    def __init__(
        self,
        application_id: int,
        application_form_url: str,
        *,
        pause_timeout_seconds: float = PAUSE_TIMEOUT_SECONDS,
    ) -> None:
        self.application_id = application_id
        self.application_form_url = application_form_url
        self._pause_timeout_seconds = pause_timeout_seconds

        self._resume_event = threading.Event()
        self.cancel_requested = threading.Event()

        self._playwright_cm = None
        self.playwright = None
        self.browser = None
        self.page = None

        # Vom Aufrufer (`start_session`) gesetzt, sobald der Thread läuft -
        # der Shutdown-Hook braucht ihn zum Joinen.
        self.thread: threading.Thread | None = None

    # --- DB-Statusübergänge --------------------------------------------

    def _set_state(self, automation_state: str, action_needed_reason: str | None) -> None:
        """Persistiert einen Automations-Statusübergang. Darf von jedem
        Thread aufgerufen werden - reine DB-Arbeit, keine Playwright-API."""
        with _db_session() as db:
            application = db.get(Application, self.application_id)
            if application is None:
                return
            application.automation_state = automation_state
            application.action_needed_reason = action_needed_reason
            if automation_state == "running" and application.automation_started_at is None:
                application.automation_started_at = datetime.now(timezone.utc)
            db.commit()

    def _abort(self, reason: str) -> None:
        """Gemeinsamer Terminal-Abbruch-Ablauf (R10/KTD1/KTD4): Browser
        schließen, `automation_state="failed"` + `reason` persistieren,
        Registry-Eintrag entfernen. Der Aufrufer wirft danach selbst die
        passende `_StopRun`-Subklasse (`PauseTimedOutError`/
        `RunCancelledError`/`IframeNotFoundError`) - dieser Schritt macht
        nur die Bereinigung gemeinsam, nicht das Werfen selbst.

        Der `_set_state()`-Aufruf ist bewusst genauso wie `close()` gegen
        eigene Fehler abgesichert (P1-Fix, reliability-reviewer): schlägt der
        DB-Schreibvorgang selbst fehl (z. B. transiente DB-Störung), muss
        `_unregister()` TROTZDEM laufen - sonst bliebe der In-Memory-
        Registry-Eintrag bis zum nächsten Prozessneustart verwaist, obwohl
        der Browser bereits geschlossen und der Thread bereits beendet ist."""
        self.close()
        try:
            self._set_state("failed", reason)
        except Exception:  # noqa: BLE001 - ein DB-Fehler darf den Registry-Cleanup nicht verhindern
            logger.exception(
                "Automations-Status (reason=%s) konnte nach Abbruch nicht persistiert werden "
                "für application_id=%s",
                reason,
                self.application_id,
            )
        _unregister(self.application_id)

    # --- Browser-Lebenszyklus (NUR vom besitzenden Thread!) -------------

    def launch(self, *, headed: bool = True) -> None:
        """Startet Chromium. Muss vom besitzenden (Hintergrund-)Thread
        aufgerufen werden. Eine Startfehlfunktion (fehlendes Display,
        fehlende Browser-Binaries, ...) propagiert als Exception."""
        if sync_playwright is None:
            raise RuntimeError("Playwright ist nicht installiert.")
        self._playwright_cm = sync_playwright()
        self.playwright = self._playwright_cm.__enter__()
        try:
            self.browser = self.playwright.chromium.launch(headless=not headed)
            self.page = self.browser.new_page()
        except Exception:
            self._playwright_cm.__exit__(None, None, None)
            self.playwright = None
            self._playwright_cm = None
            raise

    def close(self) -> None:
        """Schließt Browser/Playwright. Muss vom besitzenden Thread
        aufgerufen werden - siehe Moduldoc."""
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            if self._playwright_cm is not None:
                self._playwright_cm.__exit__(None, None, None)
            self.browser = None
            self.page = None
            self.playwright = None
            self._playwright_cm = None

    # --- Pause/Resume/Cancel --------------------------------------------

    def pause(self, reason: str) -> None:
        """Pausiert den Lauf (R10/R11): persistiert `automation_state=
        "paused"` + `reason`, dann blockiert der AUFRUFENDE (besitzende)
        Thread, bis `resume()` das Event setzt oder der Timeout abläuft.

        Läuft der Timeout ab, schließt diese Methode selbst den Browser,
        setzt `automation_state="failed"`/`"timeout"`, entfernt den
        Registry-Eintrag und wirft `PauseTimedOutError` - der Run-Loop-
        Try/Except in `start_session()` fängt das ab, ohne es nochmal als
        unhandled error zu behandeln.

        War stattdessen ein Abbruch angefordert, während pausiert wurde,
        wird das nach dem Aufwachen genauso behandelt wie `check_cancel()`.

        WICHTIG (P0-Fix, adversarial-reviewer): `_resume_event` wird HIER,
        VOR dem Persistieren des "paused"-Status und VOR `wait()`, geleert -
        nicht erst nach einem erfolgreichen Aufwachen. `_resume_event` ist
        ein einziges, über die gesamte Session-Lebensdauer geteiltes Event
        (nicht pro Pause neu erzeugt) - ohne dieses vorherige Clear kann ein
        doppelt gesendeter `resume()`-Aufruf (z. B. Doppelklick auf
        "Weiter", kein Disabled-Guard im Frontend während ein Resume-Request
        unterwegs ist) einen `.set()` hinterlassen, der NACH dieser Pause,
        aber VOR der nächsten (z. B. der zwingenden
        `pre_submit_confirmation`-Pause, R11) ankommt - die nächste Pause
        würde dann sofort durchlaufen, ohne dass für SIE tatsächlich
        `resume()` aufgerufen wurde (R11: "no setting skips this"). Da
        `threading.Event` level-getriggert (nicht edge-getriggert) ist, gibt
        es zwischen diesem `clear()` und dem `wait()` unten keine Race-Lücke -
        ein `resume()`-Aufruf genau in diesem winzigen Fenster wird von
        `wait()` trotzdem korrekt erkannt.
        """
        self._resume_event.clear()
        self._set_state("paused", reason)
        resumed = self._resume_event.wait(timeout=self._pause_timeout_seconds)
        if not resumed:
            self._abort("timeout")
            raise PauseTimedOutError()
        self._resume_event.clear()
        self.check_cancel()

    def check_cancel(self) -> None:
        """An natürlichen Checkpoints vom besitzenden Thread aufzurufen
        (nach jedem `pause()`-Aufwachen, und - analog - zwischen einzelnen
        Ausfüllschritten in späteren Units). Bricht bei gesetztem
        `cancel_requested` den Lauf sauber ab (R10)."""
        if self.cancel_requested.is_set():
            self._abort("cancelled_by_user")
            raise RunCancelledError()

    def resume(self) -> None:
        """Von außerhalb des besitzenden Threads aufzurufen (spätere API-
        Unit U6). Setzt nur das Event - fasst nie ein Playwright-Objekt an."""
        self._resume_event.set()

    def request_cancel(self) -> None:
        """Von außerhalb des besitzenden Threads aufzurufen. Setzt nur das
        Flag - fasst nie ein Playwright-Objekt an. Der Run-Loop bemerkt den
        Abbruch beim nächsten `check_cancel()`/`pause()`-Aufwachen."""
        self.cancel_requested.set()


def _unregister(application_id: int) -> None:
    with _active_sessions_lock:
        _active_sessions.pop(application_id, None)


def start_session(
    application_id: int,
    application_form_url: str,
    run_fn: Callable[[PortalFillSession], None],
    *,
    headed: bool = True,
    pause_timeout_seconds: float = PAUSE_TIMEOUT_SECONDS,
) -> PortalFillSession:
    """Startet eine neue Portal-Auto-Fill-Sitzung für `application_id`.

    Lehnt einen zweiten gleichzeitigen Start für dieselbe `application_id`
    mit `SessionAlreadyActiveError` ab. Der eigentliche Browser-Start
    (`session.launch()`) UND `run_fn` laufen komplett im neuen Hintergrund-
    Thread - dieser Aufruf blockiert nur so lange, bis der Start-Versuch
    (Erfolg ODER Fehler) feststeht, und kehrt danach sofort zurück, OHNE auf
    `run_fn` (das ggf. stundenlang auf eine Nutzeraktion wartet) zu warten.
    Schlägt der Browser-Start fehl, propagiert die Exception hier - synchron
    und klar catchbar - statt den Aufrufer im Unklaren zu lassen.
    """
    with _active_sessions_lock:
        if application_id in _active_sessions:
            raise SessionAlreadyActiveError(application_id)
        session = PortalFillSession(
            application_id, application_form_url, pause_timeout_seconds=pause_timeout_seconds
        )
        _active_sessions[application_id] = session

    launch_done = threading.Event()
    launch_error: list[BaseException] = []

    def _thread_body() -> None:
        try:
            session.launch(headed=headed)
        except Exception as exc:  # noqa: BLE001 - an den wartenden Aufrufer weiterreichen
            launch_error.append(exc)
            _unregister(application_id)
            launch_done.set()
            return

        # "running" wird VOR `launch_done.set()` persistiert: der wartende
        # `start_session()`-Aufrufer soll erst zurückkehren, nachdem der
        # DB-Status tatsächlich auf "running" steht (kein Race zwischen
        # Rückkehr und diesem Schreibvorgang).
        session._set_state("running", None)
        launch_done.set()
        try:
            run_fn(session)
        except _StopRun:
            # pause()/check_cancel() haben Browser, DB-Status und Registry
            # bereits vollständig selbst bereinigt.
            pass
        except Exception:  # noqa: BLE001 - jeder unerwartete Fehler beendet den Lauf sauber
            logger.exception(
                "Unbehandelter Fehler im Portal-Auto-Fill-Lauf für application_id=%s", application_id
            )
            try:
                session.close()
            except Exception:  # noqa: BLE001 - Schließen darf den Fehlerpfad nicht verdecken
                logger.exception("Browser konnte nach Fehler nicht sauber geschlossen werden.")
            try:
                session._set_state("failed", "unhandled_error")
            except Exception:  # noqa: BLE001 - ein DB-Fehler darf den Registry-Cleanup nicht verhindern
                logger.exception(
                    "Automations-Status konnte nach unbehandeltem Fehler nicht persistiert werden "
                    "für application_id=%s",
                    application_id,
                )
            _unregister(application_id)
        else:
            # `run_fn` ist regulär durchgelaufen (z. B. nach erfolgreichem
            # Submit) - Statuspflege (z. B. `status`/`sent_at`, R13) obliegt
            # `run_fn` selbst (spätere Units), diese Session-Verwaltung
            # entfernt hier nur den Registry-Eintrag.
            _unregister(application_id)

    thread = threading.Thread(
        target=_thread_body, name=f"portal-fill-{application_id}", daemon=True
    )
    session.thread = thread
    thread.start()

    # Blockiert nur bis der Start-Versuch feststeht (schnell: Erfolg oder
    # sofortiger Startfehler) - NICHT bis `run_fn` fertig ist.
    launch_done.wait()
    if launch_error:
        raise launch_error[0]
    return session


# --- Startup-/Shutdown-Hooks (app.main) --------------------------------


def reset_stale_automation_state() -> None:
    """Startup-Hook: setzt jede `Application` mit `automation_state` in
    ("running", "paused") auf `"failed"` zurück.

    Die In-Memory-Registry überlebt einen Prozessneustart nie - jede solche
    Zeile ist also zwangsläufig verwaist (der zugehörige Browser/Thread
    existiert nicht mehr)."""
    with _db_session() as db:
        stale = (
            db.query(Application)
            .filter(Application.automation_state.in_(["running", "paused"]))
            .all()
        )
        for application in stale:
            application.automation_state = "failed"
            application.action_needed_reason = "interrupted_by_restart"
        if stale:
            db.commit()


def shutdown_all_sessions() -> None:
    """Shutdown-Hook: fährt alle noch laufenden Sitzungen herunter.

    Fasst absichtlich NIE eine Playwright-Methode direkt an: dieser Hook
    läuft im Haupt-/Event-Loop-Thread (FastAPI-`lifespan`), der Browser
    gehört aber dem jeweiligen Session-Hintergrund-Thread - ein Cross-
    Thread-Aufruf wie `browser.close()` von hier aus wäre genau der in der
    Moduldoc beschriebene Thread-Affinitätsverstoß.

    Stattdessen wird nur signalisiert (`request_cancel()` + `resume()`, um
    einen wartenden `pause()`-Aufruf sofort aufzuwecken) und der
    besitzende Thread kurz gejoint - ER ruft dann selbst `close()` in
    seinem eigenen `check_cancel()`/`pause()`-Pfad auf. Reagiert eine
    Session innerhalb der Gnadenfrist nicht (z. B. mitten in einer
    Playwright-Aktion ohne Checkpoint), wird nur gewarnt - das OS beendet
    den Chromium-Kindprozess spätestens mit dem Elternprozess."""
    with _active_sessions_lock:
        sessions = list(_active_sessions.values())

    for session in sessions:
        session.request_cancel()
        session.resume()

    for session in sessions:
        if session.thread is not None:
            session.thread.join(timeout=SHUTDOWN_GRACE_SECONDS)
            if session.thread.is_alive():
                logger.warning(
                    "Portal-Auto-Fill-Session für application_id=%s hat sich nicht innerhalb "
                    "von %.0fs sauber beendet.",
                    session.application_id,
                    SHUTDOWN_GRACE_SECONDS,
                )
