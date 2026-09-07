from __future__ import annotations

from dataclasses import dataclass
import json
import re

from app.llm.router import LLMRouter, LLMUsage
from app.models.job import Job
from app.resumes.profile import CandidateProfile


WITHHELD_FACT_TYPES = {"identity", "contact", "address", "legal"}


@dataclass(frozen=True, slots=True)
class FactSelectionResult:
    selected_fact_ids: list[str]
    usage: LLMUsage | None
    fallback_reason: str | None = None


class LLMFactSelector:
    """Lets the model select fact IDs; candidate wording stays deterministic."""

    def __init__(self, router: LLMRouter, *, model: str = "gpt-5-nano") -> None:
        self.router = router
        self.model = model

    def select(
        self,
        *,
        job: Job,
        profile: CandidateProfile,
        candidate_fact_ids: list[str],
        stage0_passed: bool,
    ) -> FactSelectionResult:
        allowed = _allowed_facts(profile, candidate_fact_ids)
        if not allowed:
            return FactSelectionResult([], None, "NO_LLM_SAFE_FACTS")
        prompt = _selection_prompt(job, allowed)
        try:
            response = self.router.complete(
                stage="3",
                model=self.model,
                prompt=prompt,
                stage0_passed=stage0_passed,
                max_tokens=300,
            )
        except RuntimeError as exc:
            if "STAGE0" in str(exc):
                raise
            return FactSelectionResult(
                list(allowed), None, f"LLM_PROVIDER_FALLBACK:{str(exc).split(':', 1)[0]}"
            )
        try:
            selected = _parse_selection(response.text, set(allowed))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return FactSelectionResult(
                list(allowed), response.usage, f"LLM_SELECTION_INVALID:{type(exc).__name__}"
            )
        return FactSelectionResult(selected, response.usage)


def _allowed_facts(
    profile: CandidateProfile, candidate_fact_ids: list[str]
) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for fact_id in candidate_fact_ids:
        fact = profile.facts.get(fact_id)
        if (
            fact is None
            or fact.is_missing
            or fact.literal_only
            or fact.type.lower() in WITHHELD_FACT_TYPES
        ):
            continue
        allowed[fact_id] = str(fact.value)
    return allowed


def _selection_prompt(job: Job, allowed: dict[str, str]) -> str:
    job_text = _compact_job_text(job.description)
    payload = {
        "task": "Select only the candidate fact IDs most relevant to this job.",
        "rules": [
            "Return JSON only with exactly one key: selected_fact_ids.",
            "Use only IDs present in allowed_facts.",
            "Do not write or rewrite resume text.",
            "Do not infer candidate facts.",
        ],
        "job": {"title": job.title, "requirements_excerpt": job_text},
        "allowed_facts": allowed,
        "response_shape": {"selected_fact_ids": ["fact.id"]},
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _compact_job_text(description: str, limit: int = 2500) -> str:
    text = re.sub(r"\s+", " ", description).strip()
    lowered = text.lower()
    starts = [lowered.find(term) for term in ("requirements", "qualifications", "what you bring")]
    starts = [position for position in starts if position >= 0]
    if starts:
        text = text[min(starts):]
    return text[:limit]


def _parse_selection(text: str, allowed_ids: set[str]) -> list[str]:
    payload = json.loads(text)
    if not isinstance(payload, dict) or set(payload) != {"selected_fact_ids"}:
        raise ValueError("LLM_SELECTION_SCHEMA_INVALID")
    values = payload["selected_fact_ids"]
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise TypeError("LLM_SELECTION_IDS_INVALID")
    if len(values) != len(set(values)):
        raise ValueError("LLM_SELECTION_DUPLICATE_IDS")
    if not set(values).issubset(allowed_ids):
        raise ValueError("LLM_SELECTION_UNKNOWN_FACT_ID")
    return values
