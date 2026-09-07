"""Shared factories for adversarial tests (reviewer-owned, isolated from Codex modules)."""
from __future__ import annotations

from app.models.enums import JobFamily
from app.models.job import Job


def make_job(
    *,
    title: str = "Data Analyst",
    description: str = "Entry-level analytics role.",
    location: str = "Remote",
    family: JobFamily = JobFamily.DATA_ANALYTICS,
    source: str = "greenhouse",
    external_job_id: str = "1",
    apply_url: str = "https://example.test/apply/1",
    employment_type: str | None = "FULL_TIME",
    company_name: str = "Acme",
) -> Job:
    return Job(
        external_job_id=external_job_id,
        company_id="acme",
        company_name=company_name,
        title=title,
        location=location,
        description=description,
        source=source,
        source_url="https://example.test/job/1",
        apply_url=apply_url,
        ats_type=source,
        job_family=family,
        employment_type=employment_type,
    )


DATA = {"DATA_ANALYTICS"}
