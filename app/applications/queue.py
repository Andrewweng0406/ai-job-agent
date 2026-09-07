from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone

from app.matching.persona_classifier import persona_for_family
from app.models.enums import ApplicationStatus
from app.models.job import utc_now


@dataclass(frozen=True, slots=True)
class QueueResult:
    queued: int
    human_required: int


class ApplicationQueue:
    def __init__(self, repository) -> None:
        self.repository = repository

    def enqueue_eligible(self, limit: int = 100) -> QueueResult:
        rows = self.repository.get_applications_by_status(ApplicationStatus.ELIGIBLE, limit)
        queued = human_required = 0
        for row in rows:
            persona = persona_for_family(row["job_family"])
            if persona is None:
                self.repository.mark_human_required(row["application_id"], "NO_PERSONA_FOR_JOB_FAMILY")
                human_required += 1
                continue
            self.repository.update_application_context(
                row["application_id"],
                persona=persona.value,
                queued_at=utc_now().astimezone(timezone.utc).isoformat(),
            )
            self.repository.transition_application(row["application_id"], ApplicationStatus.QUEUED, "queued for resume generation")
            queued += 1
        return QueueResult(queued=queued, human_required=human_required)

