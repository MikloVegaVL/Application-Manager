"""Pluggable Captcha-Solver-Seam für den Portal-Auto-Fill-Agenten (U2/KTD2).

Definiert den `CaptchaSolver`-Vertrag und `get_captcha_solver()`, das den
Anbieter aus `settings.CAPTCHA_SOLVER_PROVIDER` liest. Der Default `"none"`
liefert KEINEN Solver - ein erkanntes Captcha eskaliert dann wie bisher als
needs-you (R5). Es wird bewusst KEIN konkreter Anbieter mitgeliefert; die Seam
existiert, damit ein späterer Solver (CapSolver/2Captcha) ohne Vertragsumbau
ergänzt werden kann.

Der Solver liefert ein explizites Ergebnis (`resolved`/`failed`/`unsupported`)
statt eines booleschen Werts (KTD2): das Widget-iframe eines gelösten Captchas
bleibt im DOM, bloße Präsenz ist also KEIN Auflösungssignal. `solve()`
bekommt nur minimalen Kontext (Seiten-URL, Sitekey, Frame-Locator), keinen
ungezügelten Seitenzugriff. `solve_captcha()` behandelt eine Exception ODER
einen Zeitüberlauf der Seam als `failed` (R6), sodass der Aufrufer nie
unbegrenzt blockiert.

Siehe docs/plans/2026-09-20-001-feat-auto-apply-hardening-plan.md (KTD2).
"""
from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CaptchaSolveStatus(str, enum.Enum):
    """Ergebnis eines Löseversuchs (KTD2)."""

    RESOLVED = "resolved"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CaptchaSolveResult:
    """Ergebnis eines `CaptchaSolver.solve()`-Aufrufs."""

    status: CaptchaSolveStatus

    @property
    def resolved(self) -> bool:
        return self.status is CaptchaSolveStatus.RESOLVED


@runtime_checkable
class CaptchaSolver(Protocol):
    """Vertrag für einen Captcha-Anbieter (KTD2).

    Erhält bewusst NUR den minimalen Kontext, den ein Anbieter braucht -
    Seiten-URL, Sitekey und den Frame-Locator des Captchas - nicht die ganze
    `Page`."""

    def solve(
        self,
        *,
        page_url: str,
        sitekey: str | None,
        frame,
        timeout_seconds: float,
    ) -> CaptchaSolveResult: ...


# Registry-Anker für einen späteren konkreten Anbieter. Bewusst leer: ohne
# Eintrag (auch für den Default "none") liefert die Fabrik `None`.
_SOLVER_FACTORIES: dict[str, Callable[[], CaptchaSolver]] = {}


def get_captcha_solver() -> CaptchaSolver | None:
    """Liefert den konfigurierten Solver oder `None` (R5).

    Der Default `"none"` sowie jeder unbekannte/leere Anbieter liefern
    `None` - ein erkanntes Captcha eskaliert dann als needs-you."""
    provider = (get_settings().CAPTCHA_SOLVER_PROVIDER or "none").strip().lower()
    factory = _SOLVER_FACTORIES.get(provider)
    return factory() if factory is not None else None


def solve_captcha(
    solver: CaptchaSolver,
    *,
    page_url: str,
    sitekey: str | None,
    frame,
    timeout_seconds: float,
) -> CaptchaSolveResult:
    """Ruft `solver.solve()` zeitlich begrenzt auf (R6/KTD2).

    Der Solver läuft in einem eigenen Worker-Thread, damit ein HÄNGENDER
    Solver den besitzenden Session-Thread nicht blockiert: `future.result
    (timeout=...)` bricht nach `timeout_seconds` ab, statt erst nach der
    Rückkehr zu prüfen. Eine Exception oder ein Überlauf gilt als `failed` -
    der Aufrufer pausiert dann, statt zu blockieren. Der Worker selbst kann
    dabei nicht mehr gestoppt werden (er wird aufgegeben); `shutdown(wait=
    False)` verhindert, dass dieser Aufruf auf ihn wartet."""

    def _call() -> CaptchaSolveResult:
        return solver.solve(
            page_url=page_url,
            sitekey=sitekey,
            frame=frame,
            timeout_seconds=timeout_seconds,
        )

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="captcha-solver")
    try:
        future = executor.submit(_call)
        try:
            result = future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            logger.warning(
                "Captcha-Solver hat das Zeitlimit von %.1fs überschritten - eskaliere als needs-you.",
                timeout_seconds,
            )
            return CaptchaSolveResult(status=CaptchaSolveStatus.FAILED)
        except Exception:  # noqa: BLE001 - jede Solver-Störung eskaliert als failed
            logger.exception("Captcha-Solver ist fehlgeschlagen - eskaliere als needs-you.")
            return CaptchaSolveResult(status=CaptchaSolveStatus.FAILED)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if not isinstance(result, CaptchaSolveResult):
        return CaptchaSolveResult(status=CaptchaSolveStatus.FAILED)
    return result
