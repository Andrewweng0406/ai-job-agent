from __future__ import annotations

from abc import ABC
from typing import Any
from urllib.parse import quote

from app.discovery.interfaces import JobSource
from app.matching.taxonomy import RoleTaxonomy
from app.models.company_registry import CompanyRegistryEntry
from app.models.job import Job
from app.utils.http import JsonHttpClient
from app.utils.text import html_to_text, normalize_employment_type


class BaseAtsJobSource(JobSource, ABC):
    def __init__(self, company: CompanyRegistryEntry, taxonomy: RoleTaxonomy, http: JsonHttpClient | None = None) -> None:
        self.company = company
        self.taxonomy = taxonomy
        self.http = http or JsonHttpClient()


class GreenhouseJobSource(BaseAtsJobSource):
    source_name = "greenhouse"

    def _list_url(self) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{quote(self.company.ats_identifier)}/jobs?content=true"

    def discover_jobs(self) -> list[dict[str, Any]]:
        payload = self.http.get_json(self._list_url())
        if not isinstance(payload, dict):
            return []
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            return []
        return [job for job in jobs if isinstance(job, dict)]

    def fetch_job(self, external_job_id: str) -> dict[str, Any]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{quote(self.company.ats_identifier)}/jobs/{quote(external_job_id)}"
        payload = self.http.get_json(url)
        if not isinstance(payload, dict):
            raise ValueError("Greenhouse job detail response was not an object")
        return payload

    def normalize_job(self, raw_job: dict[str, Any]) -> Job:
        title = str(raw_job.get("title", "")).strip()
        location = raw_job.get("location") or {}
        description = html_to_text(str(raw_job.get("content", "")))
        return Job(
            external_job_id=str(raw_job["id"]),
            company_id=self.company.company_id,
            company_name=self.company.company_name,
            title=title,
            location=str(location.get("name") or "Unknown"),
            description=description,
            source=self.source_name,
            source_url=str(raw_job.get("absolute_url") or self.company.career_url),
            apply_url=str(raw_job.get("absolute_url") or self.company.career_url),
            ats_type=self.source_name,
            job_family=self.taxonomy.classify_title(title),
            posted_at=None,
            raw_data=raw_job,
            metadata={
                "internal_job_id": raw_job.get("internal_job_id"),
                "requisition_id": raw_job.get("requisition_id"),
                "updated_at": raw_job.get("updated_at"),
            },
        )


class LeverJobSource(BaseAtsJobSource):
    source_name = "lever"

    def _list_url(self) -> str:
        return f"https://api.lever.co/v0/postings/{quote(self.company.ats_identifier)}?mode=json"

    def discover_jobs(self) -> list[dict[str, Any]]:
        payload = self.http.get_json(self._list_url())
        if isinstance(payload, list):
            postings = payload
        elif isinstance(payload, dict) and "id" in payload:
            postings = [payload]
        elif isinstance(payload, dict):
            postings = payload.get("postings", payload.get("data", payload.get("jobs", [])))
        else:
            postings = []
        if not isinstance(postings, list):
            return []
        return [job for job in postings if isinstance(job, dict)]

    def fetch_job(self, external_job_id: str) -> dict[str, Any]:
        url = f"https://api.lever.co/v0/postings/{quote(self.company.ats_identifier)}/{quote(external_job_id)}"
        payload = self.http.get_json(url)
        if not isinstance(payload, dict):
            raise ValueError("Lever job detail response was not an object")
        return payload

    def normalize_job(self, raw_job: dict[str, Any]) -> Job:
        title = str(raw_job.get("text") or raw_job.get("title") or "").strip()
        categories = raw_job.get("categories") or {}
        description = str(raw_job.get("descriptionPlain") or html_to_text(str(raw_job.get("description", ""))))
        return Job(
            external_job_id=str(raw_job["id"]),
            company_id=self.company.company_id,
            company_name=self.company.company_name,
            title=title,
            location=str(categories.get("location") or raw_job.get("location") or "Unknown"),
            description=description,
            source=self.source_name,
            source_url=str(raw_job.get("hostedUrl") or raw_job.get("applyUrl") or self.company.career_url),
            apply_url=str(raw_job.get("applyUrl") or raw_job.get("hostedUrl") or self.company.career_url),
            ats_type=self.source_name,
            job_family=self.taxonomy.classify_title(title),
            employment_type=normalize_employment_type(str(categories.get("commitment") or "")),
            raw_data=raw_job,
            metadata={"team": categories.get("team"), "created_at": raw_job.get("createdAt")},
        )


class AshbyJobSource(BaseAtsJobSource):
    source_name = "ashby"

    def _list_url(self) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{quote(self.company.ats_identifier)}?includeCompensation=true"

    def discover_jobs(self) -> list[dict[str, Any]]:
        payload = self.http.get_json(self._list_url())
        if not isinstance(payload, dict):
            return []
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            return []
        return [job for job in jobs if isinstance(job, dict) and job.get("isListed", True)]

    def fetch_job(self, external_job_id: str) -> dict[str, Any]:
        for job in self.discover_jobs():
            if str(job.get("id") or job.get("jobId") or job.get("jobUrl")) == external_job_id:
                return job
        raise KeyError(f"Unknown Ashby job id: {external_job_id}")

    def normalize_job(self, raw_job: dict[str, Any]) -> Job:
        title = str(raw_job.get("title", "")).strip()
        description = str(raw_job.get("descriptionPlain") or html_to_text(str(raw_job.get("descriptionHtml", ""))))
        compensation = raw_job.get("compensation") or {}
        salary = _extract_salary(compensation)
        external_id = str(raw_job.get("id") or raw_job.get("jobId") or raw_job.get("jobUrl"))
        return Job(
            external_job_id=external_id,
            company_id=self.company.company_id,
            company_name=self.company.company_name,
            title=title,
            location=str(raw_job.get("location") or "Unknown"),
            description=description,
            source=self.source_name,
            source_url=str(raw_job.get("jobUrl") or self.company.career_url),
            apply_url=str(raw_job.get("applyUrl") or raw_job.get("jobUrl") or self.company.career_url),
            ats_type=self.source_name,
            job_family=self.taxonomy.classify_title(title),
            remote_status=str(raw_job.get("workplaceType") or ("Remote" if raw_job.get("isRemote") else "")) or None,
            employment_type=normalize_employment_type(str(raw_job.get("employmentType") or "")),
            salary_min=salary[0],
            salary_max=salary[1],
            currency=salary[2] or "USD",
            raw_data=raw_job,
            metadata={
                "department": raw_job.get("department"),
                "team": raw_job.get("team"),
                "job_id": raw_job.get("jobId"),
                "published_at": raw_job.get("publishedAt"),
            },
        )


def _extract_salary(compensation: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    components = compensation.get("summaryComponents", [])
    if not isinstance(components, list):
        return None, None, None
    for component in components:
        if not isinstance(component, dict):
            continue
        if component.get("compensationType") == "Salary":
            return component.get("minValue"), component.get("maxValue"), component.get("currencyCode")
    return None, None, None


def source_for_company(company: CompanyRegistryEntry, taxonomy: RoleTaxonomy, http: JsonHttpClient | None = None) -> JobSource:
    match company.ats_type.lower():
        case "greenhouse":
            return GreenhouseJobSource(company, taxonomy, http)
        case "lever":
            return LeverJobSource(company, taxonomy, http)
        case "ashby":
            return AshbyJobSource(company, taxonomy, http)
        case other:
            raise ValueError(f"Unsupported ATS type for discovery: {other}")
