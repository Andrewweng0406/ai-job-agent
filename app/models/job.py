from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib
import json

from app.models.enums import JobFamily, JobStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Job:
    external_job_id: str
    company_id: str
    company_name: str
    title: str
    location: str
    description: str
    source: str
    source_url: str
    apply_url: str
    ats_type: str
    normalized_title: str | None = None
    job_family: JobFamily = JobFamily.UNKNOWN
    remote_status: str | None = None
    employment_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str = "USD"
    requirements: list[str] = field(default_factory=list)
    preferred_qualifications: list[str] = field(default_factory=list)
    posted_at: datetime | None = None
    discovered_at: datetime = field(default_factory=utc_now)
    description_hash: str | None = None
    status: JobStatus = JobStatus.NEW
    raw_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def __post_init__(self) -> None:
        if self.normalized_title is None:
            self.normalized_title = " ".join(self.title.lower().split())
        if self.description_hash is None:
            self.description_hash = stable_hash(self.description)

    @property
    def dedupe_key(self) -> str:
        parts = [
            self.external_job_id,
            self.apply_url,
            self.company_name,
            self.normalized_title or "",
            self.location,
        ]
        return stable_hash("|".join(parts))

    def metadata_json(self) -> str:
        return json.dumps(self.metadata, sort_keys=True)

