from __future__ import annotations

from dataclasses import dataclass

from app.applications.interfaces import ApplicationAdapter
from app.models.application import Application
from app.models.enums import ApplicationStatus, FailureCategory
from app.models.job import Job
from app.tracking.verification import EvidenceTier, VerificationEvidence, VerificationService
from app.resumes.profile import CandidateProfile, profile_completeness_gate


RUNNABLE_STATUSES = {ApplicationStatus.READY, ApplicationStatus.RETRY_PENDING}


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

    def run(
        self,
        application: Application,
        job: Job,
        resume_path: str,
        repository=None,
        profile: CandidateProfile | None = None,
    ) -> WorkflowResult:
        current_status = repository.get_application_status(application.application_id) if repository else application.status
        if repository is not None and current_status not in RUNNABLE_STATUSES:
            return WorkflowResult(current_status, reason=f"APPLICATION_NOT_READY:{current_status.value}")
        if repository is None and current_status in {
            ApplicationStatus.APPLYING,
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.SUBMISSION_UNKNOWN,
            ApplicationStatus.VERIFIED,
            ApplicationStatus.FAILED,
            ApplicationStatus.SKIPPED,
            ApplicationStatus.CLOSED,
        }:
            return WorkflowResult(current_status, reason=f"APPLICATION_NOT_READY:{current_status.value}")

        adapter = self.select_adapter(job)
        if adapter is None:
            application.status = ApplicationStatus.HUMAN_REQUIRED
            application.human_required_reason = "NO_SUPPORTED_APPLICATION_ADAPTER"
            if repository:
                repository.mark_human_required(application.application_id, application.human_required_reason)
            return WorkflowResult(ApplicationStatus.HUMAN_REQUIRED, reason=application.human_required_reason)
        if profile is not None:
            completeness = profile_completeness_gate(profile)
            if not completeness.complete:
                application.status = ApplicationStatus.HUMAN_REQUIRED
                application.human_required_reason = "PROFILE_INCOMPLETE"
                if repository:
                    repository.mark_human_required(application.application_id, application.human_required_reason)
                return WorkflowResult(ApplicationStatus.HUMAN_REQUIRED, reason="PROFILE_INCOMPLETE")
        if not self.real_submission_enabled:
            application.status = ApplicationStatus.HUMAN_REQUIRED
            application.human_required_reason = "REAL_SUBMISSION_DISABLED"
            if repository:
                repository.mark_human_required(application.application_id, application.human_required_reason)
            return WorkflowResult(ApplicationStatus.HUMAN_REQUIRED, reason=application.human_required_reason)

        try:
            submit_sent = False
            if current_status in RUNNABLE_STATUSES:
                _transition(repository, application, ApplicationStatus.APPLYING, "application workflow started")
            if repository:
                repository.increment_attempt_count(application.application_id)
                repository.set_applied_at_now(application.application_id)
            adapter.prepare(application)
            adapter.fill(application)
            adapter.upload_resume(application, resume_path)
            adapter.answer_questions(application)
            adapter.validate(application)
            if repository:
                repository.mark_submit_attempted(application.application_id)
            adapter.submit(application)
            submit_sent = True
            verification = adapter.verify_submission(application)
        except Exception as exc:
            application.failure_reason = str(exc)
            submit_sent = submit_sent or "SUBMIT_POST_SENT" in (application.notes or "")
            if submit_sent:
                application.status = ApplicationStatus.SUBMISSION_UNKNOWN
                application.failure_category = FailureCategory.SUBMISSION_UNKNOWN
                _transition(repository, application, ApplicationStatus.SUBMISSION_UNKNOWN, str(exc))
                return WorkflowResult(ApplicationStatus.SUBMISSION_UNKNOWN, reason=str(exc))
            application.status = ApplicationStatus.FAILED
            application.failure_category = FailureCategory.OTHER
            _transition(repository, application, ApplicationStatus.FAILED, str(exc))
            return WorkflowResult(ApplicationStatus.FAILED, reason=str(exc))

        if isinstance(verification, VerificationEvidence):
            if repository:
                _transition(repository, application, ApplicationStatus.SUBMITTED, "adapter returned verification evidence")
                status = VerificationService(repository).record_evidence(application.application_id, verification)
                application.status = status
                return WorkflowResult(status, verified=status == ApplicationStatus.VERIFIED)
            if verification.is_strong():
                application.status = ApplicationStatus.VERIFIED
                return WorkflowResult(ApplicationStatus.VERIFIED, verified=True)

        if verification is True:
            application.status = ApplicationStatus.VERIFIED
            if repository:
                _transition(repository, application, ApplicationStatus.SUBMITTED, "adapter reported submit success")
                VerificationService(repository).record_evidence(
                    application.application_id,
                    VerificationEvidence(
                        tier=EvidenceTier.T2_BACKEND_SUCCESS,
                        source=application.ats_type,
                        backend_ref="adapter_verified",
                    ),
                )
            return WorkflowResult(ApplicationStatus.VERIFIED, verified=True)
        application.status = ApplicationStatus.SUBMISSION_UNKNOWN
        _transition(repository, application, ApplicationStatus.SUBMISSION_UNKNOWN, "no reliable confirmation evidence")
        return WorkflowResult(ApplicationStatus.SUBMISSION_UNKNOWN, reason="NO_RELIABLE_CONFIRMATION_EVIDENCE")


def _transition(repository, application: Application, target: ApplicationStatus, reason: str) -> None:
    if repository is not None:
        repository.transition_application(application.application_id, target, reason)
    application.status = target
