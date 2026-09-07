"""Adversarial state-machine tests. See docs/CLAUDE_REVIEW.md P0-1 and docs/FAILURE_MODEL.md sec.4."""
from __future__ import annotations

import pytest

from app.applications.state_machine import ApplicationStateMachine, InvalidTransitionError
from app.models.enums import ApplicationStatus

M = ApplicationStateMachine()


# ADV-19 -------------------------------------------------------------------------
def test_adv19_submitted_cannot_go_to_failed():
    with pytest.raises(InvalidTransitionError):
        M.transition(ApplicationStatus.SUBMITTED, ApplicationStatus.FAILED, "late failure")


def test_retry_pending_cannot_skip_straight_to_submitted():
    with pytest.raises(InvalidTransitionError):
        M.transition(ApplicationStatus.RETRY_PENDING, ApplicationStatus.SUBMITTED, "shortcut")


# ADV-20 / P0-1: distinct unknown + verified states ---------------------------
@pytest.mark.xfail(strict=False, reason="P0-1: no SUBMISSION_UNKNOWN state; APPLYING has no unknown outcome")
def test_adv20_submission_unknown_state_exists_and_is_reachable_from_applying():
    unknown = ApplicationStatus["SUBMISSION_UNKNOWN"]
    assert M.can_transition(ApplicationStatus.APPLYING, unknown)


@pytest.mark.xfail(strict=False, reason="P0-1: SUBMITTED is terminal; cannot advance to a VERIFIED state")
def test_submitted_advances_to_verified():
    verified = ApplicationStatus["VERIFIED"]
    assert M.can_transition(ApplicationStatus.SUBMITTED, verified)


@pytest.mark.xfail(strict=False, reason="P0-1: SUBMISSION_UNKNOWN must never auto-return to APPLYING")
def test_submission_unknown_never_reenters_applying():
    unknown = ApplicationStatus["SUBMISSION_UNKNOWN"]
    assert not M.can_transition(unknown, ApplicationStatus.APPLYING)
    assert not M.can_transition(unknown, ApplicationStatus.RETRY_PENDING)


@pytest.mark.xfail(strict=False, reason="P0-1: no '* -> CLOSED' for a posting that 404s mid-flow")
@pytest.mark.parametrize("frm", [ApplicationStatus.TAILORING, ApplicationStatus.APPLYING])
def test_posting_can_close_midflow(frm):
    assert M.can_transition(frm, ApplicationStatus.CLOSED)


# Structural: every status must be a key in the transition table -------------
def test_transition_table_covers_every_status():
    from app.applications.state_machine import ALLOWED_TRANSITIONS

    missing = [s for s in ApplicationStatus if s not in ALLOWED_TRANSITIONS]
    assert not missing, f"statuses absent from ALLOWED_TRANSITIONS: {missing}"
