from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from app.models.job import Job
from app.resumes.profile import CandidateProfile


class TailoringMode(StrEnum):
    FAST = "FAST"
    DEEP = "DEEP"


@dataclass(frozen=True, slots=True)
class TailoringPlan:
    mode: TailoringMode
    requirement_keywords: list[str]
    selected_fact_ids: list[str]


class JdAwareTailoringPlanner:
    """Deterministic planner used until an LLM provider is configured."""

    def build_plan(self, job: Job, profile: CandidateProfile, mode: TailoringMode = TailoringMode.FAST) -> TailoringPlan:
        keywords = _keywords(job.description + " " + job.title)
        selected: list[str] = []
        for fact_id, fact in profile.facts.items():
            if fact.literal_only or fact.is_missing:
                continue
            haystack = " ".join([fact_id, str(fact.value), " ".join(str(v) for v in fact.raw.values())]).lower()
            if keywords & _keywords(haystack):
                selected.append(fact_id)
        if mode == TailoringMode.DEEP:
            selected.extend(
                fact_id
                for fact_id, fact in profile.facts.items()
                if not fact.literal_only and not fact.is_missing and fact_id not in selected
            )
        return TailoringPlan(mode=mode, requirement_keywords=sorted(keywords), selected_fact_ids=selected)


def _keywords(value: str) -> set[str]:
    stop = {"and", "or", "the", "with", "for", "you", "will", "role", "job", "new", "grad"}
    return {token for token in re.findall(r"[a-z0-9+#.]+", value.lower()) if len(token) > 1 and token not in stop}

