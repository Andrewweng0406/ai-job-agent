from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CompanyRegistryEntry:
    company_id: str
    company_name: str
    career_url: str
    ats_type: str
    ats_identifier: str
    active: bool = True
    industry: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

