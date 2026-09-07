from __future__ import annotations

from dataclasses import dataclass

from app.applications.interfaces import ApplicationAdapter
from app.models.application import Application
from app.models.enums import ApplicationStatus, FailureCategory
from app.models.job import Job


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    status: ApplicationStatus
    verified: bool = False
    reason: str | None = None


class ApplicationWorkflowRunner:
    def __init__(self, adapters: list[ApplicationAdapter], real_submission_enabled: bool = False) -> None:
        self.adapters = adapters
        self.real_submission_enabled = real_submission_enabled

    def select_adapter(self, job: Job) -> ApplicationAdapter | None:
        for adapter in self.adapters:
            if adapter.can_handle(job):
                return adapter
        return None

    def run(self, application: Application, job: Job, resume_path: str) -> WorkflowResult:
        adapter = self.select_adapter(job)
        if adapter is None:
            application.status = ApplicationStatus.HUMAN_REQUIRED
            application.human_required_reason = "NO_SUPPORTED_APPLICATION_ADAPTER"
            return WorkflowResult(ApplicationStatus.HUMAN_REQUIRED, reason=application.human_required_reason)
        if not self.real_submission_enabled:
            application.status = ApplicationStatus.HUMAN_REQUIRED
            application.human_required_reason = "REAL_SUBMISSION_DISABLED"
            return WorkflowResult(ApplicationStatus.HUMAN_REQUIRED, reason=application.human_required_reason)

        try:
            adapter.prepare(application)
            adapter.fill(application)
            adapter.upload_resume(application, resume_path)
            adapter.answer_questions(application)
            adapter.validate(application)
            adapter.submit(application)
            verified = adapter.verify_submission(application)
        except Exception as exc:
            application.status = ApplicationStatus.SUBMISSION_UNKNOWN
            application.failure_category = FailureCategory.SUBMISSION_UNKNOWN
            application.failure_reason = str(exc)
            return WorkflowResult(ApplicationStatus.SUBMISSION_UNKNOWN, reason=str(exc))

        if verified:
            application.status = ApplicationStatus.VERIFIED
            return WorkflowResult(ApplicationStatus.VERIFIED, verified=True)
        application.status = ApplicationStatus.SUBMISSION_UNKNOWN
        return WorkflowResult(ApplicationStatus.SUBMISSION_UNKNOWN, reason="NO_RELIABLE_CONFIRMATION_EVIDENCE")

