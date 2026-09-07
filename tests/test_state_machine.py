import pytest

from app.applications.state_machine import ApplicationStateMachine, InvalidTransitionError
from app.models.enums import ApplicationStatus


def test_valid_transition_is_recorded():
    machine = ApplicationStateMachine()
    transition = machine.transition(ApplicationStatus.DISCOVERED, ApplicationStatus.ELIGIBLE, "passed hard filters")
    assert transition.from_status == ApplicationStatus.DISCOVERED
    assert transition.to_status == ApplicationStatus.ELIGIBLE


def test_verified_is_terminal():
    machine = ApplicationStateMachine()
    transition = machine.transition(ApplicationStatus.SUBMITTED, ApplicationStatus.VERIFIED, "confirmation captured")
    assert transition.to_status == ApplicationStatus.VERIFIED
    with pytest.raises(InvalidTransitionError):
        machine.transition(ApplicationStatus.VERIFIED, ApplicationStatus.FAILED, "late failure")
