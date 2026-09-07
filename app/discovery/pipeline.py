from __future__ import annotations

from dataclasses import dataclass, field
import logging

from app.discovery.adapters import source_for_company
from app.discovery.interfaces import JobSource
from app.filtering.hard_filters import apply_hard_filters
from app.matching.taxonomy import RoleTaxonomy
from app.models.application import Application, application_dedupe_key_for_job
from app.models.company_registry import CompanyRegistryEntry
from app.models.enums import ApplicationStatus, JobStatus
from app.models.job import Job
from app.normalization.deduplication import job_identity_keys


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoveryRunSummary:
    companies_seen: int = 0
    raw_jobs_seen: int = 0
    normalized_jobs: int = 0
    new_or_updated_jobs: int = 0
    eligible_jobs: int = 0
    skipped_jobs: int = 0
    applications_created: int = 0
    errors: list[str] = field(default_factory=list)


class DiscoveryPipeline:
    def __init__(
        self,
        repository,
        taxonomy: RoleTaxonomy,
        source_factory=None,
        candidate_id: str = "default_candidate",
        requires_visa_sponsorship: bool | None = True,
    ) -> None:
        self.repository = repository
        self.taxonomy = taxonomy
        self.source_factory = source_factory or source_for_company
        self.candidate_id = candidate_id
        self.requires_visa_sponsorship = requires_visa_sponsorship

    def run(self, companies: list[CompanyRegistryEntry]) -> DiscoveryRunSummary:
        seen_keys: set[str] = set()
        summary = DiscoveryRunSummary(companies_seen=len([company for company in companies if company.active]))
        errors: list[str] = []
        raw_count = normalized_count = changed_count = eligible_count = skipped_count = created_count = 0

        for company in companies:
            if not company.active:
                continue
            try:
                source: JobSource = self.source_factory(company, self.taxonomy)
                raw_jobs = list(source.discover_jobs())
                raw_count += len(raw_jobs)
                for raw_job in raw_jobs:
                    job = source.normalize_job(raw_job)
                    normalized_count += 1
                    if set(job_identity_keys(job)) & seen_keys:
                        skipped_count += 1
                        continue
                    seen_keys.update(job_identity_keys(job))
                    job.status = self._incremental_status(job)
                    job_id = self.repository.upsert_job(job)
                    if job.status in {JobStatus.NEW, JobStatus.UPDATED}:
                        changed_count += 1
                        filter_result = apply_hard_filters(
                            job,
                            self.taxonomy.accepted_family_names(),
                            requires_visa_sponsorship=self.requires_visa_sponsorship,
                        )
                        self.repository.record_job_filter_result(job_id, filter_result.allowed, filter_result.reason)
                        if filter_result.allowed:
                            eligible_count += 1
                            if not self.repository.application_exists_for_job(job_id):
                                application = Application(
                                    job_id=job_id,
                                    company=job.company_name,
                                    position=job.title,
                                    location=job.location,
                                    job_family=job.job_family,
                                    source=job.source,
                                    ats_type=job.ats_type,
                                    dedupe_key=application_dedupe_key_for_job(job, self.candidate_id),
                                )
                                self.repository.insert_application(application)
                                self.repository.transition_application(
                                    application.application_id,
                                    ApplicationStatus.ELIGIBLE,
                                    "passed deterministic hard filters",
                                )
                                created_count += 1
                        elif filter_result.reason == "WORK_AUTHORIZATION_PROFILE_INCOMPLETE":
                            application = Application(
                                job_id=job_id,
                                company=job.company_name,
                                position=job.title,
                                location=job.location,
                                job_family=job.job_family,
                                source=job.source,
                                ats_type=job.ats_type,
                                dedupe_key=application_dedupe_key_for_job(job, self.candidate_id),
                            )
                            app_id = self.repository.insert_application(application)
                            self.repository.mark_human_required(app_id, filter_result.reason)
                            skipped_count += 1
                        else:
                            skipped_count += 1
            except Exception as exc:
                message = f"{company.company_id}: {exc}"
                logger.exception("Discovery failed", extra={"adapter": company.ats_type})
                errors.append(message)

        return DiscoveryRunSummary(
            companies_seen=summary.companies_seen,
            raw_jobs_seen=raw_count,
            normalized_jobs=normalized_count,
            new_or_updated_jobs=changed_count,
            eligible_jobs=eligible_count,
            skipped_jobs=skipped_count,
            applications_created=created_count,
            errors=errors,
        )

    def _incremental_status(self, job: Job) -> JobStatus:
        with self.repository.connect() as conn:
            row = conn.execute(
                "SELECT description_hash FROM jobs WHERE source = ? AND external_job_id = ?",
                (job.source, job.external_job_id),
            ).fetchone()
        if row is None:
            return JobStatus.NEW
        if row["description_hash"] != job.description_hash:
            return JobStatus.UPDATED
        return JobStatus.UNCHANGED
