from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from app.models.job import Job


class JobSource(ABC):
    source_name: str

    @abstractmethod
    def discover_jobs(self) -> Iterable[dict[str, Any]]:
        """Return lightweight raw job records from an allowed source."""

    @abstractmethod
    def fetch_job(self, external_job_id: str) -> dict[str, Any]:
        """Fetch a full raw job record by source-specific ID."""

    @abstractmethod
    def normalize_job(self, raw_job: dict[str, Any]) -> Job:
        """Convert raw source data into the normalized Job model."""

