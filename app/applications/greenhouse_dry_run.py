from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.applications.browser_capture import BrowserFieldCapture, PageLike
from app.applications.form_engine import FormDryRunEngine, FormDryRunResult
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.resumes.profile import CandidateProfile
from app.services.browser_hard_stop import persist_browser_hard_stop


@dataclass(frozen=True, slots=True)
class GreenhouseDryRunResult:
    status: ApplicationStatus
    dry_run: FormDryRunResult | None = None
    reason: str | None = None


class GreenhouseDryRunAdapter:
    ats_type = "greenhouse"

    def __init__(self, repository, real_submission_enabled: bool = False) -> None:
        self.repository = repository
        self.capture = BrowserFieldCapture()
        self.real_submission_enabled = real_submission_enabled
        self.submit_call_count = 0

    def dry_run(
        self,
        *,
        page: PageLike,
        application_id: str,
        job: Job,
        profile: CandidateProfile,
        resume_id: str,
        resume_path: str,
        resume_hash: str,
        resume_validation_status: str,
        persona: str | None = None,
        screenshot_path: str | Path | None = None,
    ) -> GreenhouseDryRunResult:
        capture = self.capture.capture(page, ats_type=self.ats_type, screenshot_path=screenshot_path)
        if persist_browser_hard_stop(self.repository, application_id, job.id, capture):
            return GreenhouseDryRunResult(ApplicationStatus.HUMAN_REQUIRED, reason="BROWSER_HARD_STOP")
        if not capture.fields:
            self.repository.mark_human_required(application_id, "ATS_CHANGED")
            return GreenhouseDryRunResult(ApplicationStatus.HUMAN_REQUIRED, reason="ATS_CHANGED")
        dry_run = FormDryRunEngine(self.repository, self.real_submission_enabled).build_transcript(
            application_id=application_id,
            job=job,
            profile=profile,
            resume_id=resume_id,
            resume_path=resume_path,
            resume_hash=resume_hash,
            resume_validation_status=resume_validation_status,
            persona=persona,
            fields=capture.fields,
        )
        return GreenhouseDryRunResult(dry_run.status, dry_run=dry_run)

    def submit(self) -> None:
        self.submit_call_count += 1
        raise RuntimeError("Greenhouse dry-run adapter must never submit")
