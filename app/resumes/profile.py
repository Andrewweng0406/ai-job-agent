from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.config import load_yaml


@dataclass(frozen=True, slots=True)
class CandidateFact:
    fact_id: str
    type: str
    value: Any
    required: bool = False
    literal_only: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_missing(self) -> bool:
        return self.value in (None, "", "TODO") or self.value == []


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    candidate_id: str
    schema_version: int
    facts: dict[str, CandidateFact]
    application_answers: dict[str, str]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CandidateProfile":
        data = load_yaml(path)
        meta = data.get("meta", {})
        facts: dict[str, CandidateFact] = {}
        for raw in data.get("facts", []):
            fact = CandidateFact(
                fact_id=raw["fact_id"],
                type=raw["type"],
                value=raw.get("value"),
                required=bool(raw.get("required", False)),
                literal_only=bool(raw.get("literal_only", False)),
                raw=raw,
            )
            facts[fact.fact_id] = fact
        answers = data.get("application_answers", {})
        return cls(
            candidate_id=str(meta.get("candidate_id", "TODO")),
            schema_version=int(meta.get("schema_version", 2)),
            facts=facts,
            application_answers={str(key): str(value) for key, value in answers.items()},
        )

    def required_missing_fact_ids(self) -> list[str]:
        return [fact.fact_id for fact in self.facts.values() if fact.required and fact.is_missing]

    def supported_fact_text(self, fact_ids: list[str] | None = None) -> list[str]:
        selected = fact_ids or list(self.facts)
        values: list[str] = []
        for fact_id in selected:
            fact = self.facts.get(fact_id)
            if fact is None or fact.literal_only or fact.is_missing:
                continue
            values.append(str(fact.value))
        return values


@dataclass(frozen=True, slots=True)
class ProfileCompletenessResult:
    complete: bool
    missing_fact_ids: list[str]


def profile_completeness_gate(profile: CandidateProfile) -> ProfileCompletenessResult:
    missing = profile.required_missing_fact_ids()
    return ProfileCompletenessResult(complete=not missing, missing_fact_ids=missing)

