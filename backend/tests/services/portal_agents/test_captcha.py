"""Tests für die Captcha-Solver-Seam (U2/KTD2 des Plans:
docs/plans/2026-09-20-001-feat-auto-apply-hardening-plan.md).

Deckt die U2-Testszenarien ab: Default-Anbieter liefert keinen Solver, ein
registrierter Anbieter wird gefunden, und `solve_captcha()` behandelt
Exception/Überlauf/Fehlerstatus als `failed`.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.services.portal_agents import captcha


class _StubSolver:
    def __init__(self, result=None, *, delay: float = 0.0, error: Exception | None = None):
        self._result = result
        self._delay = delay
        self._error = error
        self.calls: list[dict] = []

    def solve(self, *, page_url, sitekey, frame, timeout_seconds):
        self.calls.append(
            {
                "page_url": page_url,
                "sitekey": sitekey,
                "frame": frame,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


def _settings_with_provider(provider: str):
    return SimpleNamespace(CAPTCHA_SOLVER_PROVIDER=provider)


class TestGetCaptchaSolver:
    def test_default_provider_none_returns_no_solver(self):
        assert captcha.get_captcha_solver() is None

    def test_unknown_provider_returns_no_solver(self, mocker):
        mocker.patch.object(
            captcha, "get_settings", return_value=_settings_with_provider("mystery-provider")
        )
        assert captcha.get_captcha_solver() is None

    def test_registered_provider_returns_its_solver(self, mocker):
        solver = _StubSolver(result=captcha.CaptchaSolveResult(captcha.CaptchaSolveStatus.RESOLVED))
        mocker.patch.object(
            captcha, "get_settings", return_value=_settings_with_provider("stub")
        )
        mocker.patch.dict(captcha._SOLVER_FACTORIES, {"stub": lambda: solver})

        assert captcha.get_captcha_solver() is solver


class TestSolveCaptcha:
    def test_resolved_status_is_passed_through(self):
        result = captcha.CaptchaSolveResult(captcha.CaptchaSolveStatus.RESOLVED)
        solver = _StubSolver(result=result)

        outcome = captcha.solve_captcha(
            solver, page_url="https://x", sitekey="key", frame=object(), timeout_seconds=5.0
        )

        assert outcome is result
        assert outcome.resolved is True

    @pytest.mark.parametrize(
        "status", [captcha.CaptchaSolveStatus.FAILED, captcha.CaptchaSolveStatus.UNSUPPORTED]
    )
    def test_non_resolved_status_is_passed_through(self, status):
        result = captcha.CaptchaSolveResult(status)
        solver = _StubSolver(result=result)

        outcome = captcha.solve_captcha(
            solver, page_url="https://x", sitekey=None, frame=object(), timeout_seconds=5.0
        )

        assert outcome is result
        assert outcome.resolved is False

    def test_exception_becomes_failed(self):
        solver = _StubSolver(error=RuntimeError("provider down"))

        outcome = captcha.solve_captcha(
            solver, page_url="https://x", sitekey="key", frame=object(), timeout_seconds=5.0
        )

        assert outcome.status is captcha.CaptchaSolveStatus.FAILED

    def test_overrunning_the_bound_becomes_failed(self):
        result = captcha.CaptchaSolveResult(captcha.CaptchaSolveStatus.RESOLVED)
        solver = _StubSolver(result=result, delay=0.1)

        outcome = captcha.solve_captcha(
            solver, page_url="https://x", sitekey="key", frame=object(), timeout_seconds=0.01
        )

        assert outcome.status is captcha.CaptchaSolveStatus.FAILED

    def test_solver_receives_timeout_bound_and_minimal_context(self):
        solver = _StubSolver(result=captcha.CaptchaSolveResult(captcha.CaptchaSolveStatus.RESOLVED))
        frame = object()

        captcha.solve_captcha(
            solver, page_url="https://page", sitekey="site-key", frame=frame, timeout_seconds=42.0
        )

        assert solver.calls == [
            {
                "page_url": "https://page",
                "sitekey": "site-key",
                "frame": frame,
                "timeout_seconds": 42.0,
            }
        ]
