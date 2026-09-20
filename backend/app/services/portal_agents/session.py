"""Sitzungsverwaltung für den Portal-Auto-Fill-Agenten (U2).

Besitzt den Playwright-Browser-Lebenszyklus (Start/Pause/Resume/
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

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.application import Application
from app.services.portal_agents.outcome import (
    FailureReason,
    PauseReason,
    RunState,
)


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

# Zusätzlicher Puffer über `settings.BROWSER_LAUNCH_TIMEOUT_MS` hinaus, bevor
# `start_session()`s Backstop für einen hängenden Browser-Start greift (KTD7):
# `chromium.launch(timeout=...)` sollte selbst schon rechtzeitig werfen; der
# Backstop fängt den seltenen Fall ab, dass der Start darüber hinaus hängt.
LAUNCH_BACKSTOP_GRACE_SECONDS = 5.0

_active_sessions: dict[int, "PortalFillSession"] = {}
_active_sessions_lock = threading.Lock()


class SessionAlreadyActiveError(Exception):
    """Es läuft bereits IRGENDEIN Portal-Auto-Fill-Lauf, prozessweit (KTD10) -
    nicht mehr auf dieselbe `application_id` beschränkt, seit KTD8s fester
    Chromium-Remote-Debugging-Port keine zwei gleichzeitigen Browser-Starts
    mehr zulässt. `application_id` benennt die tatsächlich aktive Sitzung.

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


class LaunchTimedOutError(Exception):
    """Der Browser-Start hat `start_session()`s Backstop überschritten (KTD7).

    `start_session()` hat den Lauf bereits als `failed`/`browser_launch_failed`
    persistiert und den Registry-Eintrag entfernt - der wartende Aufrufer
    (API) mappt das auf einen Fehler-Response."""


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
        # KTD7: vom Backstop in `start_session()` gesetzt, wenn der Browser-
        # Start zu lange hängt - der besitzende Thread prüft das, BEVOR er
        # "running" schreibt, damit ein spät erfolgreicher Start keinen
        # Zombie-Lauf erzeugt.
        self.abandoned = threading.Event()
        # P2b: serialisiert den Check-then-act zwischen dem besitzenden Thread
        # (re-check `abandoned`, dann `running` schreiben + `launch_done`
        # setzen) und dem Backstop (Flag setzen + `failed` schreiben). Beide
        # nehmen dieselbe Lock, damit kein Interleaving einen Zombie-Lauf
        # erzeugen kann.
        self._abandon_lock = threading.Lock()
        # KTD2: nach einem erfolgreich gelösten Captcha bleibt dessen Widget-
        # iframe im DOM - dieses Flag verhindert ein erneutes Lösen/Prüfen
        # über bloße Präsenz für den Rest des Laufs.
        self.captcha_resolved = False

        self._playwright_cm = None
        self.playwright = None
        self.browser = None
        self.page = None

        # Vom Aufrufer (`start_session`) gesetzt, sobald der Thread läuft -
        # der Shutdown-Hook braucht ihn zum Joinen.
        self.thread: threading.Thread | None = None

        # R2: Screenshot der zuletzt erreichten Pause (KTD6/KTD7) - vom
        # besitzenden Thread in `pause()` gesetzt, von JEDEM Thread lesbar
        # (reine Bytes, kein Playwright-Objekt). In-Memory only, analog zur
        # restlichen Session-Registry - kein File, kein Cleanup nötig.
        self._last_screenshot: bytes | None = None

    # --- DB-Statusübergänge --------------------------------------------

    def _set_state(
        self,
        automation_state: RunState,
        action_needed_reason: PauseReason | FailureReason | None,
        action_needed_detail: str | None = None,
    ) -> None:
        """Persistiert einen Automations-Statusübergang. Darf von jedem
        Thread aufgerufen werden - reine DB-Arbeit, keine Playwright-API.

        `action_needed_detail` (R9/U7) wird bei jedem Übergang gesetzt - ohne
        Detail also auf `None` zurückgesetzt."""
        state = RunState(automation_state)
        reason = (
            action_needed_reason.value
            if isinstance(action_needed_reason, (PauseReason, FailureReason))
            else action_needed_reason
        )
        with _db_session() as db:
            application = db.get(Application, self.application_id)
            if application is None:
                return
            application.automation_state = state.value
            application.action_needed_reason = reason
            application.action_needed_detail = action_needed_detail
            if state is RunState.RUNNING and application.automation_started_at is None:
                application.automation_started_at = datetime.now(timezone.utc)
            db.commit()

    def _abort(self, reason: FailureReason) -> None:
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
            self._set_state(RunState.FAILED, FailureReason(reason))
        except Exception:  # noqa: BLE001 - ein DB-Fehler darf den Registry-Cleanup nicht verhindern
            logger.exception(
                "Automations-Status (reason=%s) konnte nach Abbruch nicht persistiert werden "
                "für application_id=%s",
                reason,
                self.application_id,
            )
        _unregister(self.application_id)

    # --- Browser-Lebenszyklus (NUR vom besitzenden Thread!) -------------

    def launch(self) -> None:
        """Startet Chromium headless. Muss vom besitzenden (Hintergrund-)
        Thread aufgerufen werden. Eine Startfehlfunktion (fehlende Browser-
        Binaries, Ressourcenknappheit, ...) propagiert als Exception.

        Der Start ist über `settings.BROWSER_LAUNCH_TIMEOUT_MS` zeitlich
        begrenzt (KTD7), damit ein hängender Chromium-Start nicht ewig
        blockiert. `--remote-debugging-port` (R3/KTD3/KTD8) läuft für die
        gesamte Lebensdauer des Browsers, nicht nur während einer Captcha-
        Pause - `start_session()`s KTD10-Guard verhindert, dass zwei Läufe
        gleichzeitig denselben festen Port belegen wollen."""
        if sync_playwright is None:
            raise RuntimeError("Playwright ist nicht installiert.")
        self._playwright_cm = sync_playwright()
        self.playwright = self._playwright_cm.__enter__()
        try:
            self.browser = self.playwright.chromium.launch(
                headless=True,
                timeout=settings.BROWSER_LAUNCH_TIMEOUT_MS,
                args=[
                    f"--remote-debugging-port={settings.PORTAL_FILL_DEBUG_PORT}",
                    "--remote-debugging-address=0.0.0.0",
                ],
            )
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

    def pause(self, reason: PauseReason, *, detail: str | None = None) -> None:
        """Pausiert den Lauf (R9/R10/R11): persistiert `automation_state=
        "paused"` + `reason` + optionales `detail` (das betroffene Feld/
        die Frage), dann blockiert der AUFRUFENDE (besitzende) Thread, bis
        `resume()` das Event setzt oder der Timeout abläuft.

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
        try:
            self._last_screenshot = self.page.screenshot()
        except Exception:  # noqa: BLE001 - eine Screenshot-Störung darf die Pause selbst nicht verhindern
            logger.exception(
                "Screenshot bei Pause (reason=%s) konnte nicht aufgenommen werden für application_id=%s",
                reason,
                self.application_id,
            )
        self._set_state(RunState.PAUSED, PauseReason(reason), detail)
        resumed = self._resume_event.wait(timeout=self._pause_timeout_seconds)
        if not resumed:
            self._abort(FailureReason.TIMEOUT)
            raise PauseTimedOutError()
        self._resume_event.clear()
        self.check_cancel()

    def screenshot_bytes(self) -> bytes | None:
        """Liefert den zuletzt bei einer Pause aufgenommenen Screenshot
        (R2/KTD6/KTD7) oder `None`, wenn noch keine Pause stattfand oder die
        Aufnahme fehlgeschlagen ist. Von JEDEM Thread aufrufbar - liest nur
        einen bereits abgelegten `bytes`-Wert, fasst kein Playwright-Objekt
        an (siehe Moduldoc R9)."""
        return self._last_screenshot

    def check_cancel(self) -> None:
        """An natürlichen Checkpoints vom besitzenden Thread aufzurufen
        (nach jedem `pause()`-Aufwachen, und - analog - zwischen einzelnen
        Ausfüllschritten in späteren Units). Bricht bei gesetztem
        `cancel_requested` den Lauf sauber ab (R10)."""
        if self.cancel_requested.is_set():
            self._abort(FailureReason.CANCELLED_BY_USER)
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

    def abandon(self) -> None:
        """Vom `start_session()`-Backstop aufzurufen, wenn der Browser-Start
        hängt (KTD7). Setzt nur ein Flag - der besitzende Thread prüft es,
        bevor er `running` schreibt, und beendet sich dann ohne weiteren
        Statuswechsel. Nimmt dieselbe Lock wie der besitzende Thread (P2b),
        damit Flag-Setzen und `running`-Schreiben nicht interleaven."""
        with self._abandon_lock:
            self.abandoned.set()


def _unregister(application_id: int) -> None:
    with _active_sessions_lock:
        _active_sessions.pop(application_id, None)


def start_session(
    application_id: int,
    application_form_url: str,
    run_fn: Callable[[PortalFillSession], None],
    *,
    pause_timeout_seconds: float = PAUSE_TIMEOUT_SECONDS,
) -> PortalFillSession:
    """Startet eine neue Portal-Auto-Fill-Sitzung für `application_id`.

    Lehnt einen zweiten gleichzeitigen Start PROZESSWEIT ab (KTD10) - nicht
    nur für dieselbe `application_id`: KTD8s fester Chromium-Remote-
    Debugging-Port kann von zwei gleichzeitigen Browser-Starts nicht beide
    gebunden werden. Der Fehler ist derselbe `SessionAlreadyActiveError`
    (409) wie zuvor, trägt aber die `application_id` der TATSÄCHLICH schon
    aktiven Sitzung (nicht der neu angeforderten), damit die Meldung
    korrekt bleibt. Der eigentliche Browser-Start (`session.launch()`) UND
    `run_fn` laufen komplett im neuen Hintergrund-Thread - dieser Aufruf
    blockiert nur so lange, bis der Start-Versuch (Erfolg ODER Fehler)
    feststeht, und kehrt danach sofort zurück, OHNE auf `run_fn` (das ggf.
    stundenlang auf eine Nutzeraktion wartet) zu warten. Schlägt der
    Browser-Start fehl, propagiert die Exception hier - synchron und klar
    catchbar - statt den Aufrufer im Unklaren zu lassen.
    """
    with _active_sessions_lock:
        if _active_sessions:
            raise SessionAlreadyActiveError(next(iter(_active_sessions)))
        session = PortalFillSession(
            application_id, application_form_url, pause_timeout_seconds=pause_timeout_seconds
        )
        _active_sessions[application_id] = session

    launch_done = threading.Event()
    launch_error: list[BaseException] = []

    def _thread_body() -> None:
        try:
            session.launch()
        except Exception as exc:  # noqa: BLE001 - an den wartenden Aufrufer weiterreichen
            launch_error.append(exc)
            # KTD7: auch ein Startfehler ist ein klassifizierter Outcome -
            # sofern der Backstop ihn nicht schon geschrieben hat. P2b: der
            # Check-then-act läuft unter derselben Lock wie der Backstop.
            with session._abandon_lock:
                if not session.abandoned.is_set():
                    try:
                        session._set_state(RunState.FAILED, FailureReason.BROWSER_LAUNCH_FAILED)
                    except Exception:  # noqa: BLE001 - ein DB-Fehler darf den Registry-Cleanup nicht verhindern
                        logger.exception(
                            "Automations-Status (browser_launch_failed) konnte nicht persistiert werden "
                            "für application_id=%s",
                            application_id,
                        )
            _unregister(application_id)
            launch_done.set()
            return

        # P2b: Re-check `abandoned` UND das `running`-Schreiben + `launch_done`
        # laufen atomar unter derselben Lock, die der Backstop zum Setzen des
        # Flags nutzt. Gewinnt der besitzende Thread die Lock zuerst, sieht der
        # Backstop `launch_done` gesetzt und schreibt kein `failed` mehr;
        # gewinnt der Backstop, sieht dieser Thread `abandoned` gesetzt und
        # schreibt kein `running` (kein Zombie-Lauf).
        with session._abandon_lock:
            if session.abandoned.is_set():
                # Der Backstop hat den Lauf bereits als
                # failed/browser_launch_failed persistiert und deregistriert -
                # hier nur noch den spät gestarteten Browser schließen.
                try:
                    session.close()
                except Exception:  # noqa: BLE001 - Schließen darf den Fehlerpfad nicht verdecken
                    logger.exception("Browser konnte nach Backstop nicht sauber geschlossen werden.")
                _unregister(application_id)
                launch_done.set()
                return

            # "running" wird VOR `launch_done.set()` persistiert: der wartende
            # `start_session()`-Aufrufer soll erst zurückkehren, nachdem der
            # DB-Status tatsächlich auf "running" steht (kein Race zwischen
            # Rückkehr und diesem Schreibvorgang).
            session._set_state(RunState.RUNNING, None)
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
                session._set_state(RunState.FAILED, FailureReason.UNHANDLED_ERROR)
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
    # sofortiger Startfehler) - NICHT bis `run_fn` fertig ist. Der Backstop
    # (KTD7) begrenzt einen hängenden Browser-Start.
    backstop_seconds = settings.BROWSER_LAUNCH_TIMEOUT_MS / 1000.0 + LAUNCH_BACKSTOP_GRACE_SECONDS
    launch_done.wait(timeout=backstop_seconds)
    if not launch_done.is_set():
        # P2b: Flag-Setzen und `failed`-Schreiben unter derselben Lock wie der
        # besitzende Thread. Das `launch_done`-Recheck INNERHALB der Lock
        # schließt die Restlücke: hat der Thread zwischen dem `wait()`-Timeout
        # und dem Lock-Erwerb doch noch `running` geschrieben + `launch_done`
        # gesetzt, darf der Backstop nicht mehr überschreiben.
        timed_out = False
        with session._abandon_lock:
            if not launch_done.is_set():
                session.abandoned.set()
                try:
                    session._set_state(RunState.FAILED, FailureReason.BROWSER_LAUNCH_FAILED)
                except Exception:  # noqa: BLE001 - ein DB-Fehler darf den Registry-Cleanup nicht verhindern
                    logger.exception(
                        "Automations-Status (browser_launch_failed) konnte nach Backstop nicht "
                        "persistiert werden für application_id=%s",
                        application_id,
                    )
                timed_out = True
        if timed_out:
            _unregister(application_id)
            raise LaunchTimedOutError(
                f"Browser-Start für application_id={application_id} hat das Zeitlimit von "
                f"{settings.BROWSER_LAUNCH_TIMEOUT_MS}ms überschritten."
            )
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
            application.automation_state = RunState.FAILED.value
            application.action_needed_reason = FailureReason.INTERRUPTED_BY_RESTART.value
            application.action_needed_detail = None
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
