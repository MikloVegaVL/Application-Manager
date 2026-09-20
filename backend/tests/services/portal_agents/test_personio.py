"""Tests für den Personio-Parser (U4).

Deckt die U4-Testszenarien des Plans ab:
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md

Läuft gegen einen ECHTEN (headless) Chromium-Browser über
`session_module.start_session(..., headed=False)` - `sync_playwright` wird
hier bewusst NICHT gemockt (im Gegensatz zu `test_session.py`), weil die
Tests echtes Cross-Frame-DOM-Verhalten prüfen wollen (Label-Assoziation
INNERHALB eines iframes, `frame_locator`-Auflösung, Captcha-Präsenz-Marker).
Das entspricht `test_base.py`s Konvention (echter Browser statt Mock), nur
zusätzlich über U2s Sitzungsverwaltung verdrahtet, damit DB-Statusübergänge
(R10/R12/KTD4) end-to-end mitgeprüft werden.

Die "Personio-iframe"-Fixture nutzt einen kleinen HTML-Trick statt eines
echten HTTP-Servers: ein `<iframe src="https://<sub>.personio.de/..."
srcdoc="...">` - der Browser rendert wegen `srcdoc` das eingebettete Markup,
das `src`-Attribut bleibt für die CSS-Attribut-Selektor-Erkennung
(`iframe[src*="personio"]`) trotzdem im DOM vorhanden. Damit lässt sich das
"cross-origin"-Muster (nur `frame_locator`, nie `page.frame(name=...)`,
erreicht das Innere) ohne Netzwerk/Server nachbilden.
"""
from __future__ import annotations

import html as html_module
import os
import tempfile
import time
import urllib.parse

import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 - registriert alle Modelle in Base.metadata
from app.db.database import Base
from app.models.application import Application
from app.models.job_offer import JobOffer
from app.models.portal_submission import PortalSubmission
from app.models.profile_attachment import ProfileAttachment
from app.services.portal_agents import base as base_module
from app.services.portal_agents import personio as personio_module
from app.services.portal_agents import session as session_module


# --- Fixtures: DB (identisches Muster zu test_session.py) -------------------


@pytest.fixture
def db_session_local():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

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
    mocker.patch.object(session_module, "SessionLocal", db_session_local)
    return db_session_local


@pytest.fixture(autouse=True)
def _clear_registry():
    session_module._active_sessions.clear()
    yield
    session_module._active_sessions.clear()


def _create_application(db_session_local) -> int:
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
        application = Application(job_offer_id=job_offer.id)
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


def _read_portal_submission(db_session_local, application_id: int) -> PortalSubmission | None:
    db = db_session_local()
    try:
        return (
            db.query(PortalSubmission)
            .filter(PortalSubmission.application_id == application_id)
            .first()
        )
    finally:
        db.close()


def _wait_for_state(db_session_local, application_id: int, state: str, timeout: float = 5.0) -> Application:
    deadline = time.monotonic() + timeout
    application = _read_application(db_session_local, application_id)
    while application.automation_state != state and time.monotonic() < deadline:
        time.sleep(0.01)
        application = _read_application(db_session_local, application_id)
    return application


# --- Fixture-Seiten: iframe via srcdoc-Trick (siehe Moduldoc) ---------------


def _iframe_page(iframe_src: str, iframe_inner_html: str) -> str:
    escaped_inner = html_module.escape(iframe_inner_html, quote=True)
    return (
        f'<html><body><iframe src="{iframe_src}" srcdoc="{escaped_inner}"></iframe></body></html>'
    )


def _data_url(html: str) -> str:
    return "data:text/html," + urllib.parse.quote(html)


FORM_FIELDS_HTML = """
<label>Full Name<input type="text" name="full_name" /></label>
<label>Email<input type="email" name="email" /></label>
<label>Country
  <select name="country">
    <option value="">Bitte wählen</option>
    <option value="DE">Germany</option>
    <option value="FR">France</option>
  </select>
</label>
<label>Resume<input type="file" name="resume" /></label>
"""


def _standard_fields(cv_path: str) -> list[personio_module.PersonioField]:
    attachment = ProfileAttachment(file_path=cv_path, filename="cv.pdf")
    return [
        personio_module.PersonioField(kind="text", value="Max Mustermann", label="Full Name"),
        personio_module.PersonioField(kind="text", value="max@example.com", label="Email"),
        personio_module.PersonioField(kind="select", value="Deutschland", label="Country"),
        personio_module.PersonioField(kind="file", value=attachment, label="Resume"),
    ]


@pytest.fixture
def cv_file(tmp_path):
    file_path = tmp_path / "cv.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")
    return str(file_path)


def _capturing_run_fn(fields, results: dict, *, iframe_wait_timeout_ms: float | None = 3000):
    """Baut ein `run_fn`, das NUR den iframe-Lokalisierungs-/Feld-Ausfüll-Teil
    der Pipeline aufruft (`_locate_frame` + `_fill_known_fields`, NICHT das
    volle `run()` mit Freitext-Entdeckung/Pre-Submit-Pause/Submit, siehe U6) -
    diese Tests decken ausschließlich U4s Zuständigkeit ab (iframe-Erkennung,
    Feld-Mapping), nicht den später (U6) angehängten Submit-Schritt.

    WICHTIG: das Auslesen von `session.page` muss im selben (besitzenden)
    Thread passieren, der `launch()` aufgerufen hat (R9-Invariante aus
    `session.py`s Moduldoc - ein Playwright-Sync-Aufruf von einem anderen
    OS-Thread aus wirft `greenlet.error`). `results` selbst ist ein reines
    Dict, das der Testthread nach `thread.join()` gefahrlos lesen kann."""

    def _run(session: session_module.PortalFillSession) -> None:
        frame = personio_module._locate_frame(session, iframe_wait_timeout_ms)
        personio_module._fill_known_fields(session, frame, fields)
        results["full_name"] = frame.get_by_label("Full Name").input_value()
        results["email"] = frame.get_by_label("Email").input_value()
        results["country"] = frame.get_by_label("Country").input_value()
        results["resume"] = frame.get_by_label("Resume").input_value()
        # Diese Tests decken nur den Ausfüll-Teil ab (kein Submit, siehe
        # Docstring oben) - hier im Test noch im besitzenden Thread
        # aufräumen, um keinen Chromium-Prozess zu leaken.
        session.close()

    return _run


# --- Happy path: Felder im Personio-iframe werden lokalisiert und gefüllt --


@pytest.mark.parametrize(
    "iframe_src",
    [
        "https://acme-corp.jobs.personio.de/job/123",
        "https://foo-bar.jobs.personio.com/job/456",
    ],
)
def test_fields_inside_personio_iframe_are_filled_via_frame_locator(
    db_session_local, cv_file, iframe_src
):
    """Happy path + Edge case: Felder werden über den frame-gebundenen
    Locator gefunden/gefüllt, unabhängig von der konkreten Employer-
    Subdomain im iframe-`src` (R3/R4)."""
    application_id = _create_application(db_session_local)
    page_html = _iframe_page(iframe_src, FORM_FIELDS_HTML)
    fields = _standard_fields(cv_file)
    results: dict = {}
    run_fn = _capturing_run_fn(fields, results)

    session = session_module.start_session(
        application_id, _data_url(page_html), run_fn, headed=False
    )
    session.thread.join(timeout=10)
    assert not session.thread.is_alive()

    assert results["full_name"] == "Max Mustermann"
    assert results["email"] == "max@example.com"
    assert results["country"] == "DE"
    assert "cv.pdf" in results["resume"]

    # Regulärer Lauf-Abschluss setzt `automation_state` selbst nicht zurück
    # (das obliegt späteren Units, z. B. dem Pre-Submit-Pause/Submit-Schritt)
    # - der Status bleibt also schlicht "running".
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "running"


# --- Error path: kein passendes iframe -> failed/iframe_not_found (KTD4) ---


def test_no_matching_iframe_fails_run_with_iframe_not_found_reason(db_session_local):
    application_id = _create_application(db_session_local)
    # Enthält "personio" NICHT im src - darf nicht gematcht werden.
    page_html = _iframe_page("https://acme.example.com/apply", FORM_FIELDS_HTML)
    run_fn = personio_module.build_personio_run_fn([], iframe_wait_timeout_ms=300)

    session = session_module.start_session(
        application_id, _data_url(page_html), run_fn, headed=False
    )
    session.thread.join(timeout=10)

    assert not session.thread.is_alive()
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "failed"
    assert application.action_needed_reason == "iframe_not_found"
    assert application_id not in session_module._active_sessions


# --- Pause path: Captcha-Präsenz pausiert vor weiterem Ausfüllen (R10) -----


def test_captcha_presence_pauses_before_any_field_is_filled(db_session_local, cv_file):
    application_id = _create_application(db_session_local)
    captcha_html = '<div class="g-recaptcha" data-sitekey="fake"></div>' + FORM_FIELDS_HTML
    page_html = _iframe_page("https://acme.jobs.personio.de/job/1", captcha_html)
    fields = _standard_fields(cv_file)
    run_fn = personio_module.build_personio_run_fn(fields, iframe_wait_timeout_ms=3000)

    session = session_module.start_session(
        application_id, _data_url(page_html), run_fn, headed=False
    )
    application = _wait_for_state(db_session_local, application_id, "paused")

    assert application.automation_state == "paused"
    assert application.action_needed_reason == "captcha"
    # Der Captcha-Check läuft VOR dem ersten Feld (`run()`s Pre-Loop-Check) -
    # es kann strukturell noch nichts ausgefüllt worden sein. (Ein direkter
    # DOM-Check von hier aus ist nicht möglich, während der besitzende Thread
    # in `pause()` blockiert - Playwrights Sync-API ist strikt an genau den
    # OS-Thread gebunden, der sie gestartet hat, siehe `session.py`s
    # Moduldoc/R9; `session.page` darf NUR aus dem `run_fn` heraus angefasst
    # werden, siehe `_capturing_run_fn` oben.)

    # Aufräumen (kein Interesse an der Fortsetzung in diesem Test - siehe
    # den Integrationstest unten für den vollen Resume-Rundlauf).
    session.request_cancel()
    session.resume()
    session.thread.join(timeout=5)


# --- Pause path: nicht gemapptes Feld pausiert mit low_confidence_field ----


def test_unmapped_field_pauses_with_low_confidence_reason(db_session_local):
    application_id = _create_application(db_session_local)
    page_html = _iframe_page("https://acme.jobs.personio.de/job/1", FORM_FIELDS_HTML)
    # "Narnia" hat keine nahe Treffer-Option im Country-Dropdown -> UNMAPPED.
    fields = [personio_module.PersonioField(kind="select", value="Narnia", label="Country")]
    run_fn = personio_module.build_personio_run_fn(fields, iframe_wait_timeout_ms=3000)

    session = session_module.start_session(
        application_id, _data_url(page_html), run_fn, headed=False
    )
    application = _wait_for_state(db_session_local, application_id, "paused")

    assert application.automation_state == "paused"
    assert application.action_needed_reason == "low_confidence_field"

    session.request_cancel()
    session.resume()
    session.thread.join(timeout=5)


# --- Integration: detect -> fill -> pause-on-captcha -> resume -> weiter ---


def test_full_detect_fill_pause_on_captcha_resume_continue_sequence(db_session_local, cv_file):
    """Detect -> pause-on-captcha -> resume -> continue filling, ohne U2/U3
    neu zu implementieren. Das Captcha-Marker-Element entfernt sich selbst
    per eingebettetem `<script>` nach einer kurzen Verzögerung - das
    simuliert "der Mensch löst das Captcha im sichtbaren Browser", OHNE dass
    der Testthread `session.page` anfassen müsste (Chromium läuft als
    eigener Prozess unabhängig vom Python-GIL/-Thread weiter, auch während
    der besitzende Thread in `pause()` blockiert - siehe R9-Hinweis oben)."""
    application_id = _create_application(db_session_local)
    self_clearing_captcha = (
        '<div class="g-recaptcha" data-sitekey="fake"></div>'
        "<script>setTimeout(() => {"
        "  var el = document.querySelector('.g-recaptcha');"
        "  if (el) { el.remove(); }"
        "}, 150);</script>"
    )
    inner_html = self_clearing_captcha + FORM_FIELDS_HTML
    page_html = _iframe_page("https://acme.jobs.personio.de/job/1", inner_html)
    fields = _standard_fields(cv_file)
    results: dict = {}
    run_fn = _capturing_run_fn(fields, results)

    session = session_module.start_session(
        application_id, _data_url(page_html), run_fn, headed=False
    )

    application = _wait_for_state(db_session_local, application_id, "paused")
    assert application.action_needed_reason == "captcha"

    # Sicherstellen, dass der eingebettete `setTimeout` bereits gefeuert hat,
    # bevor wir fortsetzen (reine Zeitsteuerung, kein Playwright-Aufruf).
    time.sleep(0.5)
    session.resume()
    session.thread.join(timeout=10)

    assert not session.thread.is_alive()
    assert results["full_name"] == "Max Mustermann"
    assert results["email"] == "max@example.com"
    assert results["country"] == "DE"
    assert "cv.pdf" in results["resume"]
    assert application_id not in session_module._active_sessions


# --- captcha_present(): reine Logik-Hilfsfunktion --------------------------


def test_captcha_present_checks_both_main_and_iframe_content():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(_iframe_page("https://x.personio.de", FORM_FIELDS_HTML))
        frame = page.frame_locator(personio_module.PERSONIO_IFRAME_SELECTOR)

        assert personio_module.captcha_present(page, frame) is False

        page.set_content(
            _iframe_page(
                "https://x.personio.de",
                '<div data-hcaptcha-widget-id="1"></div>' + FORM_FIELDS_HTML,
            )
        )
        frame = page.frame_locator(personio_module.PERSONIO_IFRAME_SELECTOR)
        assert personio_module.captcha_present(page, frame) is True

        browser.close()


# --- Freitext-Entdeckung (R7) + Pre-Submit-Pause/Submit (R11, U6) ----------
#
# Diese Tests rufen `_fill_freetext_questions()`/die volle `run()`-Pipeline
# direkt bzw. über `start_session()` auf - kein Bezug mehr zu U4s eigener
# `_capturing_run_fn`-Helper-Funktion (die deckt nur den Ausfüll-Teil ab,
# siehe deren Docstring oben).


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


def test_fill_freetext_questions_answers_unfilled_textarea_and_fills_it(
    db_session_local, page, mocker
):
    """R7: eine `<textarea>` ohne bekanntes Feld wird über
    `answer_freetext_question()` beantwortet und die Antwort landet im Feld -
    läuft direkt (kein Session-Hintergrund-Thread nötig), weil
    `_fill_freetext_questions()` selbst keine Playwright-Thread-Affinität
    voraussetzt, solange sie im selben Thread wie `page` aufgerufen wird."""
    application_id = _create_application(db_session_local)
    page.set_content(
        '<label>Full Name<input type="text" name="full_name" value="Max Mustermann" /></label>'
        '<label>Extra Frage<textarea></textarea></label>'
    )
    mock_answer = mocker.patch.object(
        personio_module, "answer_freetext_question", return_value="Meine kurze Antwort."
    )

    class _FakeSession:
        """Minimaler Stand-in für `PortalFillSession`: `_fill_freetext_questions()`
        braucht nur `.application_id`, `.page` (für den Captcha-Check) und
        `.check_cancel()` - kein echter Browser-Sitzungs-Lebenszyklus nötig,
        weil dieser Test direkt (kein Session-Hintergrund-Thread) läuft."""

        def __init__(self, application_id: int, page) -> None:
            self.application_id = application_id
            self.page = page

        def check_cancel(self) -> None:
            pass

    fake_session = _FakeSession(application_id, page)

    personio_module._fill_freetext_questions(fake_session, page)

    mock_answer.assert_called_once()
    assert mock_answer.call_args.kwargs["question"] == "Extra Frage"
    assert page.get_by_label("Extra Frage").input_value() == "Meine kurze Antwort."
    # Das bereits gefüllte Textfeld wurde von der Freitext-Entdeckung nicht
    # angerührt (es ist keine `<textarea>`, aber sicherheitshalber geprüft).
    assert page.get_by_label("Full Name").input_value() == "Max Mustermann"


FORM_FIELDS_WITH_SUBMIT_HTML = FORM_FIELDS_HTML + '<button type="submit">Submit Application</button>'


def test_mandatory_pre_submit_pause_fires_before_any_submit_click(db_session_local, cv_file):
    """R11: NACH allen Feldern (bekannt + Freitext) pausiert der Lauf IMMER
    mit `pre_submit_confirmation`, bevor der Submit-Button geklickt wird -
    kein Setting überspringt das. Der Beweis liegt in der Reihenfolge der
    beobachteten Zustände: `paused`/`pre_submit_confirmation` MUSS beobachtet
    werden, BEVOR `automation_state` auf `submitted` wechselt (das passiert
    erst nach `resume()`, siehe `_record_submission()`/`run()`)."""
    application_id = _create_application(db_session_local)
    page_html = _iframe_page("https://acme.jobs.personio.de/job/1", FORM_FIELDS_WITH_SUBMIT_HTML)
    fields = _standard_fields(cv_file)
    run_fn = personio_module.build_personio_run_fn(fields, iframe_wait_timeout_ms=3000)

    session = session_module.start_session(
        application_id, _data_url(page_html), run_fn, headed=False
    )

    application = _wait_for_state(db_session_local, application_id, "paused")
    assert application.automation_state == "paused"
    assert application.action_needed_reason == "pre_submit_confirmation"
    # Kein Submit ist bereits passiert - sonst stünde hier schon "submitted".

    session.resume()
    session.thread.join(timeout=10)

    assert not session.thread.is_alive()
    application = _read_application(db_session_local, application_id)
    assert application.automation_state == "submitted"
    assert application.action_needed_reason is None

    submission = _read_portal_submission(db_session_local, application_id)
    assert submission is not None
    assert submission.portal_url == _data_url(page_html)
    assert submission.platform == "personio"
    assert submission.company == "Acme GmbH"
    assert submission.job_title == "Backend Engineer"
    assert application_id not in session_module._active_sessions
