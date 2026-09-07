from __future__ import annotations

from dataclasses import dataclass

from app.applications.human_tasks import HumanTask
from app.applications.preview import ApplicationPreview
from app.llm.tailoring import JdAwareTailoringPlanner, TailoringMode
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import DeterministicResumeGenerator
from app.resumes.profile import CandidateProfile


@dataclass(frozen=True, slots=True)
class PrepareResult:
    preview: ApplicationPreview | None
    status: ApplicationStatus
    reason: str | None = None


class ApplicationPreparer:
    def __init__(self, repository, resume_generator: DeterministicResumeGenerator | None = None) -> None:
        self.repository = repository
        self.resume_generator = resume_generator or DeterministicResumeGenerator()
        self.tailoring = JdAwareTailoringPlanner()

    def prepare_next(self, profile: CandidateProfile, mode: TailoringMode = TailoringMode.FAST) -> PrepareResult:
        row = self.repository.get_next_application_with_job(ApplicationStatus.QUEUED)
        if row is None:
            return PrepareResult(None, ApplicationStatus.QUEUED, reason="NO_QUEUED_APPLICATION")

        application_id = row["application_id"]
        job = _job_from_row(row)
        persona = Persona(row["persona"]) if row["persona"] else _persona_from_family(job.job_family)
        if persona is None:
            self.repository.mark_human_required(
                application_id,
                "NO_PERSONA_FOR_JOB_FAMILY",
                HumanTask(
                    application_id=application_id,
                    job_id=job.id,
                    category="PROFILE_INCOMPLETE",
                    blocking_state="QUEUED",
                    prompt="No resume persona could be selected for this job family.",
                ),
            )
            return PrepareResult(None, ApplicationStatus.HUMAN_REQUIRED, reason="NO_PERSONA_FOR_JOB_FAMILY")

        self.repository.transition_application(application_id, ApplicationStatus.TAILORING, "tailoring resume")
        plan = self.tailoring.build_plan(job, profile, mode)
        result = self.resume_generator.generate(profile, job, persona, plan.selected_fact_ids)
        if result.artifact is None:
            self.repository.mark_human_required(
                application_id,
                result.human_required_reason or "RESUME_GENERATION_BLOCKED",
                HumanTask(
                    application_id=application_id,
                    job_id=job.id,
                    category=result.human_required_reason or "RESUME_GENERATION_BLOCKED",
                    blocking_state="TAILORING",
                    prompt="Resume generation requires human input before this application can proceed.",
                    context={"missing_fact_ids": result.missing_fact_ids},
                ),
            )
            return PrepareResult(None, ApplicationStatus.HUMAN_REQUIRED, reason=result.human_required_reason)

        self.repository.insert_resume_artifact(result.artifact)
        self.repository.attach_resume_to_application(application_id, result.artifact.resume_id)
        self.repository.transition_application(application_id, ApplicationStatus.READY, "resume generated and attached")
        preview = ApplicationPreview(
            company=row["company"],
            role=row["position"],
            url=row["apply_url"],
            persona=persona.value,
            resume_used=result.artifact.file_path,
            fields_filled={},
            answers=profile.application_answers,
            human_required_fields=[],
            validation_status=result.artifact.validation_status,
        )
        return PrepareResult(preview, ApplicationStatus.READY)


def _job_from_row(row) -> Job:
    return Job(
        id=row["job_id"],
        external_job_id=row["external_job_id"],
        company_id=row["company_id"],
        company_name=row["company_name"],
        title=row["title"],
        normalized_title=row["normalized_title"],
        job_family=JobFamily(row["job_family"]),
        location=row["location"],
        remote_status=row["remote_status"],
        employment_type=row["employment_type"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        currency=row["currency"],
        description=row["description"],
        source=row["source"],
        source_url=row["source_url"],
        apply_url=row["apply_url"],
        ats_type=row["ats_type"],
        description_hash=row["description_hash"],
    )


def _persona_from_family(family: JobFamily) -> Persona | None:
    try:
        return Persona(family.value.replace("DATA_ANALYTICS", "DATA"))
    except ValueError:
        return None

