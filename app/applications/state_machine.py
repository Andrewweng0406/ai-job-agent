from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import ApplicationStatus


ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: {ApplicationStatus.ELIGIBLE, ApplicationStatus.SKIPPED, ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.CLOSED},
    ApplicationStatus.ELIGIBLE: {ApplicationStatus.QUEUED, ApplicationStatus.SKIPPED, ApplicationStatus.HUMAN_REQUIRED},
    ApplicationStatus.QUEUED: {ApplicationStatus.TAILORING, ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.CLOSED},
    ApplicationStatus.TAILORING: {ApplicationStatus.READY, ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.FAILED, ApplicationStatus.CLOSED},
    ApplicationStatus.READY: {ApplicationStatus.APPLYING, ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.CLOSED},
    ApplicationStatus.APPLYING: {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.SUBMISSION_UNKNOWN,
        ApplicationStatus.FAILED,
        ApplicationStatus.RETRY_PENDING,
        ApplicationStatus.HUMAN_REQUIRED,
        ApplicationStatus.CLOSED,
    },
    ApplicationStatus.SUBMISSION_UNKNOWN: {ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.FAILED, ApplicationStatus.CLOSED},
    ApplicationStatus.RETRY_PENDING: {ApplicationStatus.APPLYING, ApplicationStatus.FAILED, ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.CLOSED},
    ApplicationStatus.HUMAN_REQUIRED: {ApplicationStatus.QUEUED, ApplicationStatus.READY, ApplicationStatus.SKIPPED, ApplicationStatus.CLOSED},
    ApplicationStatus.FAILED: {ApplicationStatus.RETRY_PENDING, ApplicationStatus.HUMAN_REQUIRED, ApplicationStatus.SKIPPED},
    ApplicationStatus.SUBMITTED: {ApplicationStatus.VERIFIED},
    ApplicationStatus.VERIFIED: set(),
    ApplicationStatus.SKIPPED: set(),
    ApplicationStatus.CLOSED: set(),
}


class InvalidTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StateTransition:
    from_status: ApplicationStatus
    to_status: ApplicationStatus
    reason: str


class ApplicationStateMachine:
    def can_transition(self, current: ApplicationStatus, target: ApplicationStatus) -> bool:
        return target in ALLOWED_TRANSITIONS[current]

    def transition(self, current: ApplicationStatus, target: ApplicationStatus, reason: str) -> StateTransition:
        if not self.can_transition(current, target):
            raise InvalidTransitionError(f"Cannot transition application from {current} to {target}")
        return StateTransition(current, target, reason)
