from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Company:
    company_id: str
    company_name: str
    career_url: str
    ats_type: str | None = None
    ats_identifier: str | None = None
    industry: str | None = None
    last_crawled_at: datetime | None = None
    crawl_status: str | None = None
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

