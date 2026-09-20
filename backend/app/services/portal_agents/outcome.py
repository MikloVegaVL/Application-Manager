"""Gemeinsames Run-Outcome-Vokabular für den Portal-Auto-Fill-Agenten (U1).

Jeder Lauf endet in GENAU EINEM expliziten Zustand (R1/R2): `RunState` deckt
die vier möglichen Werte ab, `PauseReason`/`FailureReason` die Gründe je
Zustand. Agent, Session und API lesen ihre Werte ausschließlich hier, damit
ein Lauf keinen eigenen Zustand/Grund erfinden kann (KTD1). Die String-Werte
entsprechen exakt den bisher schon persistierten Werten in
`Application.automation_state`/`action_needed_reason`.

`failure_class_for()` bildet einen Fehlgrund auf retryable/terminal ab
(KTD5). Aufrufer wenden es NUR an, wenn der Run-Zustand tatsächlich `failed`
ist - ein Pausen-Grund darf nie als terminaler Fehler gelesen werden. Ein
unbekannter Grund gilt bewusst als terminal, damit ein unerwarteter Fehler
nie automatisch erneut versucht wird.

Siehe docs/plans/2026-09-20-001-feat-auto-apply-hardening-plan.md (KTD1/KTD5).
"""
from __future__ import annotations

import enum


class RunState(str, enum.Enum):
    """Die vier expliziten Zustände eines Portal-Auto-Fill-Laufs (R1)."""

    RUNNING = "running"
    PAUSED = "paused"
    SUBMITTED = "submitted"
    FAILED = "failed"


class PauseReason(str, enum.Enum):
    """Gründe für einen `paused`-Zustand (R7/R9/R11/R12)."""

    CAPTCHA = "captcha"
    LOW_CONFIDENCE_FIELD = "low_confidence_field"
    PRE_SUBMIT_CONFIRMATION = "pre_submit_confirmation"
    DRY_RUN = "dry_run"
    SCREENING_QUESTION = "screening_question"


class FailureReason(str, enum.Enum):
    """Gründe für einen `failed`-Zustand (R3/R10)."""

    TIMEOUT = "timeout"
    IFRAME_NOT_FOUND = "iframe_not_found"
    IFRAME_UNTRUSTED_HOST = "iframe_untrusted_host"
    UNHANDLED_ERROR = "unhandled_error"
    CANCELLED_BY_USER = "cancelled_by_user"
    INTERRUPTED_BY_RESTART = "interrupted_by_restart"
    BROWSER_LAUNCH_FAILED = "browser_launch_failed"


class FailureClass(str, enum.Enum):
    """Retryability-Klassifikation eines Fehlgrunds (KTD5)."""

    RETRYABLE = "retryable"
    TERMINAL = "terminal"


# KTD5-Taxonomie: explizit retryable Gründe. Alles andere (inkl. terminal
# gelisteter und unbekannter Werte) ist terminal.
_RETRYABLE_FAILURE_REASONS = frozenset(
    {
        FailureReason.TIMEOUT,
        FailureReason.IFRAME_NOT_FOUND,
        FailureReason.UNHANDLED_ERROR,
        FailureReason.BROWSER_LAUNCH_FAILED,
        FailureReason.INTERRUPTED_BY_RESTART,
    }
)


def failure_class_for(reason: FailureReason | str | None) -> FailureClass:
    """Klassifiziert `reason` als retryable/terminal (KTD5).

    Unbekannte Werte (auch `None`) sind bewusst terminal: ein nicht
    eingeordneter Fehler wird nie automatisch erneut versucht.
    """
    try:
        normalized = FailureReason(reason)
    except ValueError:
        return FailureClass.TERMINAL
    if normalized in _RETRYABLE_FAILURE_REASONS:
        return FailureClass.RETRYABLE
    return FailureClass.TERMINAL


def run_state_for_reason(reason: PauseReason | FailureReason | str) -> RunState:
    """Der Run-Zustand, zu dem ein Grund gehört (R2/KTD1).

    `PauseReason` -> `RunState.PAUSED`, `FailureReason` -> `RunState.FAILED`.
    Wirft `ValueError` für einen unbekannten Grund.
    """
    if isinstance(reason, FailureReason):
        return RunState.FAILED
    if isinstance(reason, PauseReason):
        return RunState.PAUSED
    # Rohe Strings: zuerst gegen die Fehlgründe, dann gegen die Pausengründe
    # auflösen - die beiden Vokabulare überschneiden sich nicht.
    try:
        FailureReason(reason)
    except ValueError:
        PauseReason(reason)
        return RunState.PAUSED
    return RunState.FAILED
