from __future__ import annotations

from dataclasses import dataclass

from app.applications.form_engine import FormDryRunEngine, FormDryRunResult, InputKind, RawFormField
from app.applications.human_tasks import HumanTask
from app.applications.html_form_extractor import HtmlFormFieldExtractor
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateProfile


@dataclass(frozen=True, slots=True)
class DryRunPrepareResult:
    dry_run: FormDryRunResult | None
    status: ApplicationStatus
    reason: str | None = None


class StaticAtsFieldProvider:
    """Conservative field list used until browser enumeration is connected."""

    def fields_for(self, ats_type: str) -> list[RawFormField]:
        normalized = ats_type.lower()
        fields = [
            RawFormField("First Name", InputKind.TEXT, "profile:first_name", required=True),
            RawFormField("Last Name", InputKind.TEXT, "profile:last_name", required=True),
            RawFormField("Email", InputKind.TEXT, "profile:email", required=True),
            RawFormField("Phone", InputKind.TEXT, "profile:phone", required=True),
            RawFormField("Resume", InputKind.FILE, "application:resume", required=True),
            RawFormField("Are you authorized to work in the United States?", InputKind.SELECT, "work_auth:authorized", required=True),
            RawFormField("Will you now or in the future require sponsorship?", InputKind.SELECT, "work_auth:sponsorship", required=True),
            RawFormField("LinkedIn URL", InputKind.TEXT, "links:linkedin", required=False),
            RawFormField("GitHub URL", InputKind.TEXT, "links:github", required=False),
        ]
        if normalized == "lever":
            fields.append(RawFormField("Additional information", InputKind.LONG_TEXT, "lever:comments", required=False))
        if normalized == "greenhouse":
            fields.append(RawFormField("How did you hear about us?", InputKind.SELECT, "greenhouse:source", required=False))
        if normalized == "ashby":
            fields.append(RawFormField("Website", InputKind.TEXT, "ashby:website", required=False))
        return fields


class HtmlAtsFieldProvider:
    def __init__(self, html_by_ats: dict[str, str]) -> None:
        self.html_by_ats = html_by_ats
        self.extractor = HtmlFormFieldExtractor()

    def fields_for(self, ats_type: str) -> list[RawFormField]:
        html = self.html_by_ats.get(ats_type.lower()) or self.html_by_ats.get(ats_type)
        if not html:
            return StaticAtsFieldProvider().fields_for(ats_type)
        return self.extractor.extract(html, ats_type)


class ApplicationDryRunPreparer:
    def __init__(self, repository, field_provider: StaticAtsFieldProvider | None = None, real_submission_enabled: bool = False) -> None:
        self.repository = repository
        self.field_provider = field_provider or StaticAtsFieldProvider()
        self.real_submission_enabled = real_submission_enabled

    def dry_run_next(self, profile: CandidateProfile) -> DryRunPrepareResult:
        row = self.repository.get_next_application_with_job(ApplicationStatus.READY)
        if row is None:
            return DryRunPrepareResult(None, ApplicationStatus.READY, "NO_READY_APPLICATION")
        if not row["resume_id"] or not row["resume_file_path"] or not row["resume_file_hash"]:
            self.repository.mark_human_required(
                row["application_id"],
                "RESUME_ARTIFACT_MISSING",
                HumanTask(
                    application_id=row["application_id"],
                    job_id=row["job_id"],
                    category="RESUME_ARTIFACT_MISSING",
                    blocking_state=ApplicationStatus.READY.value,
                    prompt="A ready application is missing a validated resume artifact.",
                ),
            )
            return DryRunPrepareResult(None, ApplicationStatus.HUMAN_REQUIRED, "RESUME_ARTIFACT_MISSING")
        job = _job_from_row(row)
        dry_run = FormDryRunEngine(self.repository, self.real_submission_enabled).build_transcript(
            application_id=row["application_id"],
            job=job,
            profile=profile,
            resume_id=row["resume_id"],
            resume_path=row["resume_file_path"],
            resume_hash=row["resume_file_hash"],
            fields=self.field_provider.fields_for(job.ats_type),
        )
        return DryRunPrepareResult(dry_run, dry_run.status)


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
