"""Tests für die Portal-Auto-Fill-API (U6):
docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md

Nutzt die `StaticPool` + Non-Context-Manager-`TestClient`-Fixture aus
`tests/api/test_jobs.py` (siehe dessen Moduldoc-Hinweis: `TestClient`
dispatched Requests auf einem Worker-Thread, `SingletonThreadPool` bricht
dabei; `with TestClient(app):` würde zusätzlich die echte Lifespan/
`init_db()` gegen die echte App-DB auslösen - beides hier vermieden).

`sync_playwright` wird NICHT durch reine `MagicMock`-Objekte ersetzt (das
wäre für diese DOM-lastige Pipeline - Label-Matching, `<select>`-Optionen,
Textarea-Discovery, Submit-Button-Lookup - fragiler als der Nutzen): dieses
Modul nutzt stattdessen einen dünnen Proxy um das ECHTE `sync_playwright()`
(dasselbe Muster wie `test_personio.py`/`test_session.py`), der lediglich
(a) `headless=True` erzwingt (die Produktionsroute `POST .../start` ruft
`start_session()` ohne `headed=False` auf - ein echtes, sichtbares
Chromium-Fenster wäre in CI nicht akzeptabel) und (b) die Formular-URL (die
laut Endpoint-Vertrag `https://` sein MUSS, siehe KTD11) per
`page.route()` mit einer lokalen Fixture-Seite beantwortet, statt einen
echten Netzwerk-Request zu senden. `llm_client.generate_structured` wird
zusätzlich gemockt (siehe `client`-Fixture), obwohl die Happy-Path-Fixture
keine Freitext-`<textarea>` enthält - reine Absicherung gegen einen
versehentlichen echten LLM-Aufruf.
"""
from __future__ import annotations

import html as html_module
import os
import tempfile
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 - registriert alle Modelle in Base.metadata
from app.db.database import Base, get_db
from app.main import app
from app.models.application import Application
from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.models.portal_submission import PortalSubmission
from app.services.portal_agents import answering as answering_module
from app.services.portal_agents import session as session_module

APPLICATION_FORM_URL = "https://acme.example.com/apply"
IFRAME_SRC = "https://acme-corp.jobs.personio.de/job/123"
FORM_HTML = (
    '<label>Name<input type="text" name="full_name" /></label>'
    '<label>Email<input type="email" name="email" /></label>'
    '<button type="submit">Submit Application</button>'
)


def _iframe_page(iframe_src: str, iframe_inner_html: str) -> str:
    """Identischer srcdoc-Trick wie in `test_personio.py`s Moduldoc: simuliert
    ein cross-origin Personio-iframe ohne echten HTTP-Server."""
    escaped_inner = html_module.escape(iframe_inner_html, quote=True)
    return f'<html><body><iframe src="{iframe_src}" srcdoc="{escaped_inner}"></iframe></body></html>'


PAGE_HTML = _iframe_page(IFRAME_SRC, FORM_HTML)


def _patch_playwright_with_routed_page(mocker, url: str, html_body: str) -> None:
    """Patcht `session_module.sync_playwright` auf einen dünnen Proxy um das
    ECHTE `sync_playwright()` - siehe Moduldoc oben für die Begründung.

    `goto(url)` wird auf `page.set_content(html_body)` umgeleitet, wenn die
    URL passt (statt sie über `page.route()`/einen echten Netzwerk-Request
    zu beantworten): ein `page.route()`-Ansatz erwies sich in dieser
    Sandbox als flaky (Race zwischen Routing-Setup und Chromiums eigenem
    Versuch, die - real nicht auflösbare - Domain zu kontaktieren, je nach
    Timing gelegentlich als `unhandled_error` statt eines geroutet
    beantworteten Requests beobachtet). `set_content()` ist rein lokal (kein
    Netzwerk, kein Timing-Fenster) und identisch zu `test_base.py`s/
    `test_personio.py`s eigener Konvention (`data:`-URLs/`set_content()`
    statt echter Requests)."""
    from playwright.sync_api import sync_playwright as real_sync_playwright

    class _StubbedGotoPage:
        def __init__(self, page):
            self._page = page

        def goto(self, target_url, **kwargs):
            if target_url == url:
                return self._page.set_content(html_body)
            return self._page.goto(target_url, **kwargs)

        def __getattr__(self, name):
            return getattr(self._page, name)

    class _RoutedBrowser:
        def __init__(self, browser):
            self._browser = browser

        def new_page(self):
            return _StubbedGotoPage(self._browser.new_page())

        def close(self):
            self._browser.close()

    class _RoutedChromium:
        def __init__(self, chromium):
            self._chromium = chromium

        def launch(self, **kwargs):
            kwargs["headless"] = True  # nie ein sichtbares Fenster in Tests/CI
            return _RoutedBrowser(self._chromium.launch(**kwargs))

    class _RoutedPlaywright:
        def __init__(self, playwright):
            self.chromium = _RoutedChromium(playwright.chromium)

    class _RoutedPlaywrightCM:
        def __enter__(self):
            self._cm = real_sync_playwright()
            return _RoutedPlaywright(self._cm.__enter__())

        def __exit__(self, *exc_info):
            return self._cm.__exit__(*exc_info)

    mocker.patch.object(session_module, "sync_playwright", lambda: _RoutedPlaywrightCM())


@pytest.fixture
def db_session_local():
    # EIGENE dateibasierte SQLite-Engine statt `:memory:` + `StaticPool` (wie
    # `test_jobs.py`) - mit voller Absicht, siehe `test_session.py`s
    # Moduldoc: diese Tests schreiben/lesen von ECHT unterschiedlichen
    # Threads gleichzeitig (Session-Hintergrund-Thread via `_set_state()`/
    # `_record_submission()` UND der Testthread/Request-Handler-Thread über
    # `get_db()`). Ein einzelnes, über `StaticPool` geteiltes `:memory:`-
    # Connection-Objekt ist dabei NICHT threadsicher seriell nutzbar (führte
    # hier zu einem intermittenten `database is locked`/verlorenen Commits,
    # sichtbar als flaky 409-/submitted-Assertions) - eine echte Datei gibt
    # jeder Session ihre eigene Connection, wie gegen eine echte Produktiv-DB.
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


@pytest.fixture
def client(db_session_local, mocker):
    def _override_get_db():
        db = db_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # `session._set_state()`/personio.pys neue Helfer (`_load_answering_
    # context`/`_record_submission`) schreiben über `session_module.
    # SessionLocal()` - dieselbe Test-Engine wie die `get_db`-Overrides oben,
    # sonst würden Hintergrund-Thread-Schreibvorgänge in einer anderen
    # (echten App-)DB landen.
    mocker.patch.object(session_module, "SessionLocal", db_session_local)
    mocker.patch.object(
        answering_module.llm_client,
        "generate_structured",
        return_value=SimpleNamespace(answer="Mocked LLM answer."),
    )
    session_module._active_sessions.clear()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        session_module._active_sessions.clear()


def _seed_job_offer_and_application(db_session_local) -> int:
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


def _seed_profile(db_session_local, **overrides) -> None:
    defaults = dict(full_name="Max Mustermann", email="max@example.com")
    defaults.update(overrides)
    db = db_session_local()
    try:
        db.add(MasterProfile(**defaults))
        db.commit()
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


def _wait_for_state(db_session_local, application_id: int, state: str, timeout: float = 10.0) -> Application:
    deadline = time.monotonic() + timeout
    application = _read_application(db_session_local, application_id)
    while application.automation_state != state and time.monotonic() < deadline:
        time.sleep(0.02)
        application = _read_application(db_session_local, application_id)
    return application


# --- Happy path: start -> running -> paused/pre_submit_confirmation -> ------
# --- continue -> submitted, PortalSubmission-Zeile + Application-Relation --


def test_happy_path_start_status_continue_to_submitted(client, db_session_local, mocker):
    application_id = _seed_job_offer_and_application(db_session_local)
    _seed_profile(db_session_local)
    _patch_playwright_with_routed_page(mocker, APPLICATION_FORM_URL, PAGE_HTML)

    start_resp = client.post(
        f"/api/applications/{application_id}/portal-fill/start",
        json={"application_form_url": APPLICATION_FORM_URL},
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["automation_state"] == "running"

    application = _wait_for_state(db_session_local, application_id, "paused")
    assert application.automation_state == "paused"
    assert application.action_needed_reason == "pre_submit_confirmation"

    status_resp = client.get(f"/api/applications/{application_id}/portal-fill/status")
    assert status_resp.status_code == 200
    assert status_resp.json() == {
        "automation_state": "paused",
        "action_needed_reason": "pre_submit_confirmation",
    }

    continue_resp = client.post(f"/api/applications/{application_id}/portal-fill/continue")
    assert continue_resp.status_code == 200

    application = _wait_for_state(db_session_local, application_id, "submitted")
    assert application.automation_state == "submitted"
    assert application.action_needed_reason is None

    # Integration: das bestehende `GET /applications/{id}` spiegelt den neuen
    # Status wider, und die `PortalSubmission`-Zeile ist über die Relation
    # sichtbar (Snapshot-Felder aus dem `JobOffer`).
    get_resp = client.get(f"/api/applications/{application_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["automation_state"] == "submitted"

    submission = _read_portal_submission(db_session_local, application_id)
    assert submission is not None
    assert submission.application_id == application_id
    assert submission.platform == "personio"
    assert submission.company == "Acme GmbH"
    assert submission.job_title == "Backend Engineer"
    assert submission.portal_url == APPLICATION_FORM_URL


# --- Edge case: zweiter Start während eine Sitzung aktiv ist -> 409 --------


def test_second_start_while_active_returns_409(client, db_session_local, mocker):
    """Deckt ausschließlich die 409-Dedup-Logik ab (`_generating_lock`-Muster
    aus `send_application`), NICHT die volle Fill-Pipeline - der `run_fn` wird
    hier durch einen simplen, sofort pausierenden Stand-in ersetzt (kein
    `page.goto`/Feld-Matching o. ä.), damit dieser Test nicht von echtem
    DOM-/Browser-Timing abhängt (das würde einen zweiten, gleichzeitig
    laufenden echten Chromium-Prozess nur unnötig fragil machen - die reale
    Fill-Pipeline deckt bereits `test_happy_path_...` end-to-end ab)."""
    application_id = _seed_job_offer_and_application(db_session_local)
    _seed_profile(db_session_local)
    # Der `goto`-Stub aus `_patch_playwright_with_routed_page` wird vom
    # Stand-in-`run_fn` unten nie ausgelöst (er fasst `session.page` gar
    # nicht an) - wiederverwendet wird hier nur dessen `headless=True`-
    # Erzwingung, statt sie ein zweites Mal zu implementieren.
    _patch_playwright_with_routed_page(mocker, APPLICATION_FORM_URL, PAGE_HTML)
    mocker.patch(
        "app.api.portal_fill.personio_module.build_personio_run_fn",
        return_value=lambda session: session.pause("captcha"),
    )

    first_resp = client.post(
        f"/api/applications/{application_id}/portal-fill/start",
        json={"application_form_url": APPLICATION_FORM_URL},
    )
    assert first_resp.status_code == 200

    # Erst auf den stabilen (weiterhin registrierten) `paused`-Zustand
    # warten, statt die zweite Anfrage direkt im Anschluss an `first_resp` zu
    # feuern - macht den Test unabhängig vom exakten Timing zwischen
    # "running" (Rückgabe von `first_resp`) und dem sofortigen `pause()` des
    # Stand-in-`run_fn`.
    application = _wait_for_state(db_session_local, application_id, "paused")
    assert application.automation_state == "paused"

    second_resp = client.post(
        f"/api/applications/{application_id}/portal-fill/start",
        json={"application_form_url": APPLICATION_FORM_URL},
    )
    assert second_resp.status_code == 409

    # Aufräumen: die erste Sitzung bis zum Abschluss laufen lassen, damit kein
    # Chromium-Prozess/Hintergrund-Thread über das Testende hinaus lebt.
    session = session_module._active_sessions.get(application_id)
    if session is not None:
        session.request_cancel()
        session.resume()
        session.thread.join(timeout=5)


# --- Edge case: http:// (nicht-https) wird VOR jedem Session-Start abgelehnt


def test_start_with_non_https_url_is_rejected_before_any_session(client, db_session_local):
    application_id = _seed_job_offer_and_application(db_session_local)
    _seed_profile(db_session_local)

    resp = client.post(
        f"/api/applications/{application_id}/portal-fill/start",
        json={"application_form_url": "http://acme.example.com/apply"},
    )

    assert resp.status_code == 422
    assert application_id not in session_module._active_sessions
    application = _read_application(db_session_local, application_id)
    assert application.automation_state is None


# --- Error path: continue/cancel ohne aktive Sitzung -> 404 -----------------


def test_continue_without_active_session_returns_404(client, db_session_local):
    application_id = _seed_job_offer_and_application(db_session_local)

    resp = client.post(f"/api/applications/{application_id}/portal-fill/continue")

    assert resp.status_code == 404


def test_cancel_without_active_session_returns_404(client, db_session_local):
    application_id = _seed_job_offer_and_application(db_session_local)

    resp = client.post(f"/api/applications/{application_id}/portal-fill/cancel")

    assert resp.status_code == 404


def test_status_for_missing_application_returns_404(client):
    resp = client.get("/api/applications/999999/portal-fill/status")

    assert resp.status_code == 404
