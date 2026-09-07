from __future__ import annotations

from pathlib import Path

from app.models.enums import JobFamily
from app.utils.config import load_yaml


class RoleTaxonomy:
    def __init__(self, accepted_families: dict[str, dict[str, object]]) -> None:
        self.accepted_families = accepted_families

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RoleTaxonomy":
        data = load_yaml(path)
        return cls(data.get("accepted_job_families", {}))

    def accepted_family_names(self) -> set[str]:
        return set(self.accepted_families)

    def classify_title(self, title: str) -> JobFamily:
        normalized = " ".join(title.lower().split())
        for family_name, config in self.accepted_families.items():
            keywords = config.get("title_keywords", [])
            if not isinstance(keywords, list):
                continue
            for keyword in keywords:
                if str(keyword).lower() in normalized:
                    return JobFamily(family_name)
        return JobFamily.UNKNOWN

