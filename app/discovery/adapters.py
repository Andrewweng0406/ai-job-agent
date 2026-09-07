from __future__ import annotations

from abc import ABC
from datetime import datetime, timezone
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
            posted_at=parse_datetime(raw_job.get("updated_at")),
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
            posted_at=parse_datetime(raw_job.get("createdAt")),
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
            posted_at=parse_datetime(raw_job.get("publishedAt")),
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


class SmartRecruitersJobSource(BaseAtsJobSource):
    source_name = "smartrecruiters"

    def _list_url(self) -> str:
        return f"https://api.smartrecruiters.com/v1/companies/{quote(self.company.ats_identifier)}/postings?limit=100&offset=0"

    def discover_jobs(self) -> list[dict[str, Any]]:
        payload = self.http.get_json(self._list_url())
        if not isinstance(payload, dict):
            return []
        jobs = payload.get("content", [])
        if not isinstance(jobs, list):
            return []
        return [job for job in jobs if isinstance(job, dict)]

    def fetch_job(self, external_job_id: str) -> dict[str, Any]:
        url = f"https://api.smartrecruiters.com/v1/companies/{quote(self.company.ats_identifier)}/postings/{quote(external_job_id)}"
        payload = self.http.get_json(url)
        if not isinstance(payload, dict):
            raise ValueError("SmartRecruiters job detail response was not an object")
        return payload

    def normalize_job(self, raw_job: dict[str, Any]) -> Job:
        title = str(raw_job.get("name") or raw_job.get("title") or "").strip()
        location = raw_job.get("location") or {}
        sections = raw_job.get("jobAd", {}).get("sections", {})
        description = "\n".join(
            html_to_text(section.get("text", ""))
            for section in sections.values()
            if isinstance(section, dict)
        )
        loc_text = ", ".join(str(part) for part in [location.get("city"), location.get("region")] if part)
        return Job(
            external_job_id=str(raw_job["id"]),
            company_id=self.company.company_id,
            company_name=self.company.company_name,
            title=title,
            location=loc_text or str(location.get("country") or "Unknown"),
            description=description or title,
            source=self.source_name,
            source_url=str(raw_job.get("ref") or raw_job.get("applyUrl") or self.company.career_url),
            apply_url=str(raw_job.get("applyUrl") or raw_job.get("ref") or self.company.career_url),
            ats_type=self.source_name,
            job_family=self.taxonomy.classify_title(title),
            posted_at=parse_datetime(raw_job.get("releasedDate")),
            raw_data=raw_job,
            metadata={"requisition_id": raw_job.get("refNumber"), "uuid": raw_job.get("uuid")},
        )


class WorkdayJobSource(BaseAtsJobSource):
    source_name = "workday"

    def _list_url(self) -> str:
        return f"https://{quote(self.company.ats_identifier)}.myworkdayjobs.com/wday/cxs/{quote(self.company.ats_identifier)}/jobs"

    def discover_jobs(self) -> list[dict[str, Any]]:
        payload = self.http.get_json(self._list_url())
        if not isinstance(payload, dict):
            return []
        jobs = payload.get("jobPostings", [])
        if not isinstance(jobs, list):
            return []
        return [job for job in jobs if isinstance(job, dict)]

    def fetch_job(self, external_job_id: str) -> dict[str, Any]:
        payload = self.http.get_json(f"{self._list_url()}/{quote(external_job_id.strip('/'))}")
        if not isinstance(payload, dict):
            raise ValueError("Workday job detail response was not an object")
        return payload

    def normalize_job(self, raw_job: dict[str, Any]) -> Job:
        detail = self.fetch_job(str(raw_job.get("externalPath") or raw_job.get("id") or ""))
        info = detail.get("jobPostingInfo", detail)
        title = str(info.get("title") or raw_job.get("title") or "").strip()
        external_id = str(info.get("jobRequisitionId") or info.get("id") or raw_job.get("externalPath"))
        description = html_to_text(str(info.get("jobDescription") or ""))
        return Job(
            external_job_id=external_id,
            company_id=self.company.company_id,
            company_name=self.company.company_name,
            title=title,
            location=str(info.get("location") or raw_job.get("locationsText") or "Unknown"),
            description=description or title,
            source=self.source_name,
            source_url=str(info.get("externalUrl") or self.company.career_url),
            apply_url=str(info.get("externalUrl") or self.company.career_url),
            ats_type=self.source_name,
            job_family=self.taxonomy.classify_title(title),
            employment_type=normalize_employment_type(str(info.get("timeType") or "")),
            posted_at=parse_datetime(info.get("postedOn") or info.get("startDate")),
            raw_data={"list": raw_job, "detail": detail},
            metadata={"requisition_id": external_id, "external_path": raw_job.get("externalPath")},
        )


def source_for_company(company: CompanyRegistryEntry, taxonomy: RoleTaxonomy, http: JsonHttpClient | None = None) -> JobSource:
    match company.ats_type.lower():
        case "greenhouse":
            return GreenhouseJobSource(company, taxonomy, http)
        case "lever":
            return LeverJobSource(company, taxonomy, http)
        case "ashby":
            return AshbyJobSource(company, taxonomy, http)
        case "smartrecruiters":
            return SmartRecruitersJobSource(company, taxonomy, http)
        case "workday":
            return WorkdayJobSource(company, taxonomy, http)
        case other:
            raise ValueError(f"Unsupported ATS type for discovery: {other}")


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, "", "TODO"):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    text = str(value).strip()
    if not text or text.lower().startswith("posted "):
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
