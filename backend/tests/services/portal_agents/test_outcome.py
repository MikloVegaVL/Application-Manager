"""Tests für das gemeinsame Run-Outcome-Vokabular (U1 des Plans:
docs/plans/2026-09-20-001-feat-auto-apply-hardening-plan.md).

Deckt die U1-Testszenarien ab: String-Werte, Zustands-Zuordnung der Gründe,
die Retryable/Terminal-Taxonomie (KTD5) sowie die Spaltenlängen-Grenzen.
"""
from __future__ import annotations

import pytest

from app.models.application import Application
from app.services.portal_agents import outcome

# Die Spalten, in denen die Vokabular-Werte landen (siehe
# `app.models.application`): `automation_state` ist `String(20)`,
# `action_needed_reason` ist `String(30)`.
_STATE_MAX_LENGTH = Application.__table__.c.automation_state.type.length
_REASON_MAX_LENGTH = Application.__table__.c.action_needed_reason.type.length


def test_run_state_string_values_match_persisted_values():
    assert {state.value for state in outcome.RunState} == {
        "running",
        "paused",
        "submitted",
        "failed",
    }


def test_pause_reasons_are_exactly_the_pause_causes():
    assert {reason.value for reason in outcome.PauseReason} == {
        "captcha",
        "low_confidence_field",
        "pre_submit_confirmation",
        "dry_run",
        "screening_question",
    }


def test_failure_reasons_include_launch_and_untrusted_host():
    assert {reason.value for reason in outcome.FailureReason} == {
        "timeout",
        "iframe_not_found",
        "iframe_untrusted_host",
        "unhandled_error",
        "cancelled_by_user",
        "interrupted_by_restart",
        "browser_launch_failed",
    }


@pytest.mark.parametrize("reason", list(outcome.PauseReason))
def test_every_pause_reason_maps_to_paused(reason):
    assert outcome.run_state_for_reason(reason) is outcome.RunState.PAUSED


@pytest.mark.parametrize("reason", list(outcome.FailureReason))
def test_every_failure_reason_maps_to_failed(reason):
    assert outcome.run_state_for_reason(reason) is outcome.RunState.FAILED


@pytest.mark.parametrize(
    "reason",
    [
        outcome.FailureReason.TIMEOUT,
        outcome.FailureReason.IFRAME_NOT_FOUND,
        outcome.FailureReason.UNHANDLED_ERROR,
        outcome.FailureReason.BROWSER_LAUNCH_FAILED,
        outcome.FailureReason.INTERRUPTED_BY_RESTART,
    ],
)
def test_retryable_reasons_classify_as_retryable(reason):
    assert outcome.failure_class_for(reason) is outcome.FailureClass.RETRYABLE


@pytest.mark.parametrize(
    "reason",
    [
        outcome.FailureReason.CANCELLED_BY_USER,
        outcome.FailureReason.IFRAME_UNTRUSTED_HOST,
    ],
)
def test_terminal_reasons_classify_as_terminal(reason):
    assert outcome.failure_class_for(reason) is outcome.FailureClass.TERMINAL


def test_unknown_reason_string_defaults_to_terminal():
    assert outcome.failure_class_for("not_a_real_reason") is outcome.FailureClass.TERMINAL
    assert outcome.failure_class_for(None) is outcome.FailureClass.TERMINAL


def test_untrusted_host_is_terminal_but_missing_iframe_is_retryable():
    assert (
        outcome.failure_class_for(outcome.FailureReason.IFRAME_UNTRUSTED_HOST)
        is outcome.FailureClass.TERMINAL
    )
    assert (
        outcome.failure_class_for(outcome.FailureReason.IFRAME_NOT_FOUND)
        is outcome.FailureClass.RETRYABLE
    )


def test_state_and_reason_values_fit_their_columns():
    for state in outcome.RunState:
        assert len(state.value) <= _STATE_MAX_LENGTH
    for reason in (*outcome.PauseReason, *outcome.FailureReason):
        assert len(reason.value) <= _REASON_MAX_LENGTH
