from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.models.enums import ApplicationStatus, FailureCategory, JobFamily, Persona
from app.models.job import Job, stable_hash


@dataclass(slots=True)
class Application:
    job_id: int
    company: str
    position: str
    location: str
    job_family: JobFamily
    source: str
    ats_type: str
    application_id: str = field(default_factory=lambda: str(uuid4()))
    dedupe_key: str | None = None
    match_score: float | None = None
    persona: Persona | None = None
    resume_id: str | None = None
    discovered_at: datetime | None = None
    queued_at: datetime | None = None
    applied_at: datetime | None = None
    submission_verified_at: datetime | None = None
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    attempt_count: int = 0
    failure_category: FailureCategory | None = None
    failure_reason: str | None = None
    human_required_reason: str | None = None
    confirmation_data: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None


def requisition_key_for_job(job: Job) -> str:
    for key in ("requisition_id", "internal_job_id", "job_id", "jobId", "posting_id"):
        value = job.metadata.get(key)
        if value not in (None, "", "TODO"):
            return f"{job.ats_type}:{value}"
    return f"{job.ats_type}:{job.external_job_id}"


def application_dedupe_key_for_job(job: Job, candidate_id: str) -> str:
    stable_candidate = candidate_id if candidate_id and candidate_id != "TODO" else "default_candidate"
    return stable_hash("|".join([stable_candidate, job.company_id, requisition_key_for_job(job)]))
