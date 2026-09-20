"""Tests für die Portal-Auto-Fill-Sitzungsverwaltung (U2).

Deckt die U2-Testszenarien des Plans ab:
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md

Mockt `sync_playwright` nach demselben Muster wie
`tests/services/job_sources/test_shared.py` (`_fake_playwright` +
Context-Manager-Fake), damit kein echter Chromium gestartet wird.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 - registriert alle Modelle in Base.metadata
from app.db.database import Base
from app.models.application import Application
from app.models.job_offer import JobOffer
from app.services.portal_agents import session as session_module
from app.services.portal_agents.outcome import FailureClass, failure_class_for


# --- Fixtures: DB + Playwright-Fake -----------------------------------------


@pytest.fixture
def db_session_local():
    """Eigene dateibasierte SQLite-Engine (statt `:memory:` + `StaticPool`
    wie in `tests/api/test_applications.py`): diese Tests lesen/schreiben
    von ECHT unterschiedlichen Threads gleichzeitig (Test-Thread pollt,
    Session-Hintergrund-Thread schreibt via `_set_state()`). Ein einzelnes,
    über `StaticPool` geteiltes `:memory:`-Connection-Objekt wird dabei nicht
    threadsicher seriell benutzt (SQLAlchemy verwaltet dessen Transaktionen
    selbst) - ein Schreibvorgang aus Thread B kann für einen parallel
    lesenden Thread A dadurch unsichtbar bleiben. Eine echte Datei erlaubt
    stattdessen jeder Session ihre eigene Connection, wie es auch gegen eine
    echte Produktiv-DB der Fall wäre."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        engine.dispose()
        os.unlink(path)


@pytest.fixture(autouse=True)
def _patch_session_local(db_session_local, mocker):
    """Lässt `session._set_state()`/die Hooks gegen die Test-DB statt die
    echte App-DB schreiben."""
    mocker.patch.object(session_module, "SessionLocal", db_session_local)
    return db_session_local


@pytest.fixture(autouse=True)
def _clear_registry():
    """Verhindert, dass ein Test-Leck (z. B. ein Timeout) die Registry für
    den nächsten Test verschmutzt."""
    session_module._active_sessions.clear()
    yield
    session_module._active_sessions.clear()


def _create_application(db_session_local, *, automation_state: str | None = None) -> int:
    db = db_session_local()
    try:
        job_offer = JobOffer(
            title="Backend Engineer",
            company="Acme GmbH",
            source_url="https://example.com/jobs/1",
            source_platform="personio",
        )
        db.add(job_offer)
        db.flush()
        application = Application(job_offer_id=job_offer.id, automation_state=automation_state)
        db.add(application)
        db.commit()
        db.refresh(application)
        return application.id
    finally:
        db.close()


def _read_application(db_session_local, application_id: int) -> Application:
    db = db_session_local()
    try:
        return db.get(Application, application_id)
    finally:
        db.close()


def _fake_playwright() -> tuple[MagicMock, MagicMock]:
    """Baut ein Fake-`sync_playwright()`-Ergebnis analog zu
    `test_shared.py::_fake_playwright`, gibt zusätzlich den `browser`-Mock
    zurück, damit Tests `browser.close.assert_called_once()` prüfen können."""
    page = MagicMock()
    browser = MagicMock()
    browser.new_page = MagicMock(return_value=page)
    browser.close = MagicMock()

    playwright = MagicMock()
    playwright.chromium.launch = MagicMock(return_value=browser)

    playwright_cm = MagicMock()
    playwright_cm.__enter__ = MagicMock(return_value=playwright)
    playwright_cm.__exit__ = MagicMock(return_value=False)

    sync_playwright_factory = MagicMock(return_value=playwright_cm)
    return sync_playwright_factory, browser


def _patch_sync_playwright(mocker, sync_playwright_factory) -> None:
    mocker.patch.object(session_module, "sync_playwright", sync_playwright_factory)


# --- Platzhalter-`run_fn`s zum Durchspielen der Maschinerie -----------------


def _pausing_run_fn(reason: str = "captcha"):
    def _run(session: session_module.PortalFillSession) -> None:
        session.pause(reason)

    return _run


def _looping_run_fn(steps: int = 200, delay: float = 0.01, started: threading.Event | None = None):
    """Läuft in kleinen Schritten und prüft `check_cancel()` zwischen jedem
    Schritt - genau das Muster, das echtes Feld-Ausfüllen (U4) später auch
    verwenden wird."""

    def _run(session: session_module.PortalFillSession) -> None:
        if started is not None:
            started.set()
        for _ in range(steps):
            session.check_cancel()
            time.sleep(delay)

    return _run


def _crashing_run_fn():
    def _run(session: session_module.PortalFillSession) -> None:
        raise RuntimeError("boom")

    return _run


# --- Happy path: start ------------------------------------------------------


def test_start_session_sets_automation_state_running(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    # Ein `run_fn`, das (im Gegensatz zu `_pausing_run_fn`) nicht sofort in
    # "paused" weiterspringt, damit der Test den "running"-Zwischenstatus
    # zuverlässig beobachten kann, statt in ein Race mit dem nächsten
    # Übergang zu laufen. `start_session()` kehrt erst zurück, NACHDEM
    # "running" persistiert wurde (siehe Kommentar in `session.py`).
    session = session_module.start_session(
        application_id, "https://portal.example/apply", _looping_run_fn(steps=1000, delay=0.005)
    )

    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "running"

    # Aufräumen.
    session.request_cancel()
    session.thread.join(timeout=2)


def test_second_concurrent_start_for_same_application_is_rejected(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    started = threading.Event()
    session = session_module.start_session(
        application_id, "https://portal.example/apply", _looping_run_fn(started=started)
    )
    started.wait(timeout=2)

    with pytest.raises(session_module.SessionAlreadyActiveError):
        session_module.start_session(
            application_id, "https://portal.example/apply", _looping_run_fn()
        )

    session.request_cancel()
    session.thread.join(timeout=2)


# --- Happy path: pause/resume ------------------------------------------------


def test_pause_sets_state_and_resume_unblocks_the_owning_thread(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("low_confidence_field")
    )

    # Auf den paused-Status warten (Thread braucht einen Moment).
    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)

    assert application.automation_state == "paused"
    assert application.action_needed_reason == "low_confidence_field"

    session.resume()
    session.thread.join(timeout=2)
    assert not session.thread.is_alive()
    # Registry wurde nach regulärem Lauf-Ende bereinigt.
    assert application_id not in session_module._active_sessions


# --- R2/KTD6/KTD7: Screenshot bei Pause --------------------------------------


def test_pause_captures_screenshot_bytes(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    browser.new_page.return_value.screenshot = MagicMock(return_value=b"fake-png-bytes")
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("dry_run")
    )

    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)

    assert session.screenshot_bytes() == b"fake-png-bytes"

    session.resume()
    session.thread.join(timeout=2)


def test_pause_survives_a_screenshot_failure(db_session_local, mocker):
    """P1-Fix-Analogie zu `_abort()`: eine fehlgeschlagene Screenshot-Aufnahme
    darf die Pause selbst (Statuswechsel + Warten auf Resume) nicht
    verhindern."""
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    browser.new_page.return_value.screenshot = MagicMock(side_effect=RuntimeError("boom"))
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("dry_run")
    )

    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)

    assert application.automation_state == "paused"
    assert session.screenshot_bytes() is None

    session.resume()
    session.thread.join(timeout=2)
    assert not session.thread.is_alive()


def test_duplicate_resume_during_gap_between_pauses_does_not_skip_the_next_pause(
    db_session_local, mocker
):
    """P0-Regression (adversarial-reviewer): ein Doppelklick auf "Weiter"
    (kein Disabled-Guard im Frontend während ein Resume-Request unterwegs
    ist) kann zwei `resume()`-Aufrufe für DENSELBEN Pause-Schritt auslösen.
    Landet der zweite (überzählige) Aufruf NACH dem Aufwachen der ersten
    Pause, aber BEVOR die nächste (hier: die zwingende
    `pre_submit_confirmation`-Pause, R11) zu warten beginnt, darf er diese
    nächste Pause NICHT vorzeitig auflösen - sonst würde die
    Pflichtbestätigung vor dem echten Submit stillschweigend übersprungen.
    `pause()` leert `_resume_event` deshalb jetzt VOR jedem `wait()` (nicht
    erst danach), damit ein solcher "stale" Set-Zustand verworfen wird."""
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    gap_reached = threading.Event()
    allow_second_pause = threading.Event()

    def _run(session: session_module.PortalFillSession) -> None:
        session.pause("captcha")
        gap_reached.set()
        allow_second_pause.wait(timeout=5)
        session.pause("pre_submit_confirmation")

    session = session_module.start_session(application_id, "https://portal.example/apply", _run)

    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)
    assert application.action_needed_reason == "captcha"

    # Erster Klick: löst die captcha-Pause auf.
    session.resume()
    assert gap_reached.wait(timeout=2)

    # Doppelklick-Simulation: EIN zweiter, überzähliger `resume()`-Aufruf,
    # während der Lauf sich noch in der Lücke zwischen den beiden Pausen
    # befindet (noch nicht bei `pre_submit_confirmation` angekommen).
    session.resume()

    # Jetzt erst darf der Lauf in die nächste (zwingende) Pause eintreten.
    allow_second_pause.set()

    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.action_needed_reason != "pre_submit_confirmation" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)
    assert application.automation_state == "paused"
    assert application.action_needed_reason == "pre_submit_confirmation"

    # Der überzählige `resume()` darf diese Pause NICHT bereits aufgelöst
    # haben - kurz stabil bleiben lassen und erneut prüfen.
    time.sleep(0.2)
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "paused"
    assert application.action_needed_reason == "pre_submit_confirmation"

    # Erst ein DRITTER, expliziter `resume()`-Aufruf löst diese Pause auf.
    session.resume()
    session.thread.join(timeout=2)
    assert not session.thread.is_alive()
    assert application_id not in session_module._active_sessions


# --- Edge case: cancel während running/paused -------------------------------


def test_cancel_while_paused_closes_browser_from_owning_thread_and_marks_failed(
    db_session_local, mocker
):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("captcha")
    )

    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)
    assert application.automation_state == "paused"

    owning_thread_ident_before = session.thread.ident
    session.request_cancel()
    # `resume()` weckt den wartenden `pause()`-Aufruf sofort auf - ohne das
    # müsste der Test bis PAUSE_TIMEOUT_SECONDS warten.
    session.resume()
    session.thread.join(timeout=2)

    assert not session.thread.is_alive()
    # `browser.close()` wurde aufgerufen - und zwar vom besitzenden Thread
    # selbst (derselbe Thread, der `launch()` ausgeführt hat), nie vom
    # Testthread aus direkt an `session.browser` vorbei.
    browser.close.assert_called_once()
    assert threading.current_thread().ident != owning_thread_ident_before

    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "cancelled_by_user"
    assert application_id not in session_module._active_sessions


def test_cancel_while_running_is_noticed_at_the_next_checkpoint(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    started = threading.Event()
    session = session_module.start_session(
        application_id,
        "https://portal.example/apply",
        _looping_run_fn(steps=1000, delay=0.005, started=started),
    )
    started.wait(timeout=2)

    session.request_cancel()
    session.thread.join(timeout=2)

    assert not session.thread.is_alive()
    browser.close.assert_called_once()
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "cancelled_by_user"


# --- Error path: Launch-Fehler ----------------------------------------------


def test_launch_failure_surfaces_synchronously_from_start_session(db_session_local, mocker):
    playwright_cm = MagicMock()
    playwright_cm.__enter__ = MagicMock(side_effect=RuntimeError("no display available"))
    playwright_cm.__exit__ = MagicMock(return_value=False)
    factory = MagicMock(return_value=playwright_cm)
    _patch_sync_playwright(mocker, factory)

    application_id = _create_application(db_session_local)

    with pytest.raises(RuntimeError, match="no display available"):
        session_module.start_session(
            application_id, "https://portal.example/apply", _pausing_run_fn()
        )

    assert application_id not in session_module._active_sessions
    # KTD7: ein Startfehler wird jetzt als klassifizierter Outcome
    # persistiert (retryable) - nicht mehr als "kein Status".
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "browser_launch_failed"


# --- Error path: unbehandelter Fehler mitten im Lauf ------------------------


def test_unhandled_exception_mid_run_marks_application_failed(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _crashing_run_fn()
    )
    session.thread.join(timeout=2)

    assert not session.thread.is_alive()
    browser.close.assert_called_once()
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "unhandled_error"
    assert application_id not in session_module._active_sessions


# --- Error path: Pause-Timeout -----------------------------------------------


def test_pause_timeout_marks_application_failed_with_timeout_reason(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id,
        "https://portal.example/apply",
        _pausing_run_fn("captcha"),
        pause_timeout_seconds=0.05,
    )
    session.thread.join(timeout=2)

    assert not session.thread.is_alive()
    browser.close.assert_called_once()
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "timeout"
    assert application_id not in session_module._active_sessions


def test_abort_unregisters_session_even_if_set_state_db_write_fails(db_session_local, mocker):
    """P1-Regression (reliability-reviewer): schlägt der `_set_state()`-DB-
    Schreibvorgang im Abbruch-/Cleanup-Pfad selbst fehl (z. B. transiente
    DB-Störung), darf der In-Memory-Registry-Eintrag TROTZDEM nicht
    verwaisen - sonst bliebe `application_id` bis zum nächsten
    Prozessneustart fälschlich als "aktiv" markiert und ein erneuter
    `start_session()`-Aufruf würde dauerhaft mit
    `SessionAlreadyActiveError` fehlschlagen, obwohl Browser/Thread längst
    beendet sind."""
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    # Nur die "failed"-Transition (der Abbruch-/Cleanup-Pfad) schlägt fehl -
    # "running"/"paused" müssen weiterhin normal funktionieren, damit der
    # Lauf überhaupt bis zum Abbruch-Pfad kommt, den dieser Test prüft.
    original_set_state = session_module.PortalFillSession._set_state

    def _flaky_set_state(self, automation_state, action_needed_reason, action_needed_detail=None):
        if automation_state == "failed":
            raise RuntimeError("DB ist gerade nicht erreichbar")
        return original_set_state(self, automation_state, action_needed_reason, action_needed_detail)

    mocker.patch.object(session_module.PortalFillSession, "_set_state", _flaky_set_state)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("captcha")
    )
    session.request_cancel()
    session.resume()
    session.thread.join(timeout=2)

    assert not session.thread.is_alive()
    # Der Registry-Eintrag wurde entfernt, OBWOHL der DB-Schreibvorgang im
    # Abbruch-Pfad geworfen hat - ein erneuter Start für dieselbe
    # `application_id` muss deshalb wieder möglich sein.
    assert application_id not in session_module._active_sessions
    factory2, browser2 = _fake_playwright()
    _patch_sync_playwright(mocker, factory2)
    second_session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("captcha")
    )
    second_session.request_cancel()
    second_session.resume()
    second_session.thread.join(timeout=2)


# --- Integration: Startup-Hook (verwaister Zustand nach Neustart) ----------


@pytest.mark.parametrize("stale_state", ["running", "paused"])
def test_startup_hook_resets_stale_automation_state_with_no_registry_entry(
    db_session_local, stale_state
):
    application_id = _create_application(db_session_local, automation_state=stale_state)
    # Kein Registry-Eintrag - simuliert einen Prozessneustart.
    assert application_id not in session_module._active_sessions

    session_module.reset_stale_automation_state()

    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"


def test_startup_hook_leaves_other_states_untouched(db_session_local):
    application_id = _create_application(db_session_local, automation_state="failed")

    session_module.reset_stale_automation_state()

    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"


# --- Integration: Shutdown-Hook ---------------------------------------------


def test_shutdown_hook_closes_browser_of_a_paused_session_via_its_owning_thread(
    db_session_local, mocker
):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("captcha")
    )
    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)
    assert application.automation_state == "paused"

    calling_thread_ident = threading.current_thread().ident

    # Der Shutdown-Hook selbst ruft NIE `browser.close()` auf - er
    # signalisiert nur (`request_cancel`/`resume`) und joint den Thread, der
    # `close()` dann selbst aufruft. Das wird hier über die Mock-Call-Args
    # nicht direkt unterscheidbar, ist aber durch den Produktivcode
    # garantiert (siehe `shutdown_all_sessions`-Docstring) - dieser Test
    # verifiziert lediglich das beobachtbare Ergebnis: `close()` wurde
    # aufgerufen und der Thread ist danach beendet.
    session_module.shutdown_all_sessions()

    assert not session.thread.is_alive()
    browser.close.assert_called_once()
    assert threading.current_thread().ident == calling_thread_ident

    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "cancelled_by_user"


def test_shutdown_hook_closes_browser_of_a_running_session(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    started = threading.Event()
    session = session_module.start_session(
        application_id,
        "https://portal.example/apply",
        _looping_run_fn(steps=1000, delay=0.005, started=started),
    )
    started.wait(timeout=2)

    session_module.shutdown_all_sessions()

    assert not session.thread.is_alive()
    browser.close.assert_called_once()


# --- U3/KTD7: begrenzter Browser-Start --------------------------------------


def test_launch_passes_configured_timeout_to_chromium(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)
    mocker.patch.object(session_module.settings, "BROWSER_LAUNCH_TIMEOUT_MS", 12345)

    session = session_module.start_session(
        application_id,
        "https://portal.example/apply",
        _looping_run_fn(steps=1000, delay=0.005),
    )

    playwright = factory.return_value.__enter__.return_value
    playwright.chromium.launch.assert_called_once_with(headless=True, timeout=12345)

    session.request_cancel()
    session.thread.join(timeout=2)


def test_launch_backstop_marks_failed_and_never_writes_running(db_session_local, mocker):
    """KTD7: hängt der Browser-Start über den Backstop hinaus, persistiert
    `start_session()` sofort `failed`/`browser_launch_failed` und
    deregistriert; der spät erfolgreiche Start darf danach KEIN `running`
    mehr schreiben."""
    application_id = _create_application(db_session_local)
    release = threading.Event()

    def _slow_enter():
        release.wait(timeout=5)
        playwright = MagicMock()
        browser = MagicMock()
        browser.new_page = MagicMock(return_value=MagicMock())
        playwright.chromium.launch = MagicMock(return_value=browser)
        return playwright

    playwright_cm = MagicMock()
    playwright_cm.__enter__ = MagicMock(side_effect=_slow_enter)
    playwright_cm.__exit__ = MagicMock(return_value=False)
    factory = MagicMock(return_value=playwright_cm)
    _patch_sync_playwright(mocker, factory)
    mocker.patch.object(session_module.settings, "BROWSER_LAUNCH_TIMEOUT_MS", 50)
    mocker.patch.object(session_module, "LAUNCH_BACKSTOP_GRACE_SECONDS", 0.05)

    started = time.monotonic()
    with pytest.raises(session_module.LaunchTimedOutError):
        session_module.start_session(
            application_id, "https://portal.example/apply", _looping_run_fn()
        )
    elapsed = time.monotonic() - started

    assert elapsed < 2
    assert application_id not in session_module._active_sessions
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "browser_launch_failed"
    assert (
        failure_class_for(application.action_needed_reason) is FailureClass.RETRYABLE
    )

    # Den blockierten Thread jetzt freigeben - sein späterer Erfolg darf den
    # Status nicht mehr auf "running" zurücksetzen.
    release.set()
    for thread in threading.enumerate():
        if thread.name == f"portal-fill-{application_id}":
            thread.join(timeout=5)
            break
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "browser_launch_failed"


# --- U3/KTD5: Fehlklassifikation an den bestehenden Ausgängen ---------------


def test_startup_hook_records_interrupted_by_restart_as_retryable(db_session_local):
    application_id = _create_application(db_session_local, automation_state="paused")

    session_module.reset_stale_automation_state()

    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "interrupted_by_restart"
    assert (
        failure_class_for(application.action_needed_reason) is FailureClass.RETRYABLE
    )


def test_cancelled_by_user_is_terminal(db_session_local, mocker):
    application_id = _create_application(db_session_local)
    factory, browser = _fake_playwright()
    _patch_sync_playwright(mocker, factory)

    session = session_module.start_session(
        application_id, "https://portal.example/apply", _pausing_run_fn("captcha")
    )
    deadline = time.monotonic() + 2
    application = _read_application(db_session_local, application_id)
    while application.automation_state != "paused" and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)

    session.request_cancel()
    session.resume()
    session.thread.join(timeout=2)

    application = _read_application(db_session_local, application_id)
    assert application.action_needed_reason == "cancelled_by_user"
    assert failure_class_for(application.action_needed_reason) is FailureClass.TERMINAL
