from __future__ import annotations

from pathlib import Path

from app.models.company_registry import CompanyRegistryEntry
from app.utils.config import load_yaml


def load_company_registry(path: str | Path) -> list[CompanyRegistryEntry]:
    data = load_yaml(path)
    entries: list[CompanyRegistryEntry] = []
    for raw in data.get("companies", []):
        entries.append(
            CompanyRegistryEntry(
                company_id=raw["company_id"],
                company_name=raw["company_name"],
                career_url=raw["career_url"],
                ats_type=raw["ats_type"].lower(),
                ats_identifier=raw["ats_identifier"],
                active=bool(raw.get("active", True)),
                industry=raw.get("industry"),
                metadata=raw.get("metadata", {}),
            )
        )
    return entries

