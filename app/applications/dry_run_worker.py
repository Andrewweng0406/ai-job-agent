from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.applications.ashby_dry_run import AshbyDryRunAdapter
from app.applications.ats_dom_dry_run import AtsDomDryRunAdapter
from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.applications.lever_dry_run import LeverDryRunAdapter
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateProfile


PageProvider = Callable[[str, Job], object]


@dataclass(frozen=True, slots=True)
class DryRunWorkerResult:
    status: ApplicationStatus
    application_id: str | None = None
    reason: str | None = None


class DryRunApplicationWorker:
    def __init__(
        self,
        repository,
        *,
        worker_id: str,
        profile: CandidateProfile,
        page_provider: PageProvider,
        real_submission_enabled: bool = False,
        lease_seconds: int = 120,
        adapters: dict[str, AtsDomDryRunAdapter] | None = None,
    ) -> None:
        if real_submission_enabled:
            raise ValueError("Dry-run workers require real_submission_enabled=False")
        self.repository = repository
        self.worker_id = worker_id
        self.profile = profile
        self.page_provider = page_provider
        self.real_submission_enabled = False
        self.lease_seconds = lease_seconds
        self.adapters = adapters or {
            "greenhouse": GreenhouseDryRunAdapter(repository, real_submission_enabled=real_submission_enabled),
            "lever": LeverDryRunAdapter(repository, real_submission_enabled=real_submission_enabled),
            "ashby": AshbyDryRunAdapter(repository, real_submission_enabled=real_submission_enabled),
        }

    def run_once(self) -> DryRunWorkerResult:
        lease_until = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
        claimed = self.repository.claim_next_application(ApplicationStatus.READY, self.worker_id, lease_until)
        if claimed is None:
            return DryRunWorkerResult(ApplicationStatus.READY, reason="NO_READY_APPLICATION")
        application_id, lease_epoch = claimed
        if not self.repository.lease_still_mine(application_id, self.worker_id, lease_epoch):
            return DryRunWorkerResult(ApplicationStatus.APPLYING, application_id, reason="LEASE_LOST")
        row = self.repository.get_application_with_job(application_id)
        if row is None:
            self.repository.release_lease(application_id, self.worker_id, lease_epoch)
            return DryRunWorkerResult(ApplicationStatus.FAILED, application_id, reason="APPLICATION_NOT_FOUND")
        job = _job_from_row(row)
        adapter = self.adapters.get(job.ats_type)
        if adapter is None:
            self.repository.mark_human_required(application_id, "NO_SUPPORTED_APPLICATION_ADAPTER")
            self.repository.release_lease(application_id, self.worker_id, lease_epoch)
            return DryRunWorkerResult(ApplicationStatus.HUMAN_REQUIRED, application_id, "NO_SUPPORTED_APPLICATION_ADAPTER")
        page = self.page_provider(application_id, job)
        if not self.repository.lease_still_mine(application_id, self.worker_id, lease_epoch):
            return DryRunWorkerResult(ApplicationStatus.APPLYING, application_id, reason="LEASE_LOST")
        result = adapter.dry_run(
            page=page,
            application_id=application_id,
            job=job,
            profile=self.profile,
            resume_id=row["resume_id"] or "",
            resume_path=row["resume_file_path"] or "",
            resume_hash=row["resume_file_hash"] or "",
            resume_validation_status=row["resume_validation_status"] or "MISSING",
            persona=row["persona"],
        )
        if result.status == ApplicationStatus.READY and self.repository.lease_still_mine(application_id, self.worker_id, lease_epoch):
            self.repository.transition_application(application_id, ApplicationStatus.READY, "dry-run worker completed without submit")
        self.repository.release_lease(application_id, self.worker_id, lease_epoch)
        return DryRunWorkerResult(result.status, application_id, result.reason)


def _job_from_row(row) -> Job:
    job = Job(
        external_job_id=row["external_job_id"],
        company_id=row["company_id"],
        company_name=row["company_name"],
        title=row["title"],
        location=row["location"],
        description=row["description"],
        source=row["source"],
        source_url=row["source_url"],
        apply_url=row["apply_url"],
        ats_type=row["ats_type"],
        normalized_title=row["normalized_title"],
        job_family=JobFamily(row["job_family"]),
        remote_status=row["remote_status"],
        employment_type=row["employment_type"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        currency=row["currency"],
        description_hash=row["description_hash"],
        id=row["job_id"],
    )
    return job
