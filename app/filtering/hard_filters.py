from __future__ import annotations

from dataclasses import dataclass
import re

from app.models.job import Job


SENIORITY_PATTERN = re.compile(r"\b(senior|sr\.?|staff|principal|director|vp|executive|head of)\b", re.I)
CLEARANCE_PATTERN = re.compile(
    r"\b(active\s+)?(top secret|ts/sci|secret)\s+clearance\b|\bsecurity clearance\b",
    re.I,
)
US_CITIZEN_PATTERN = re.compile(
    r"\b(us|u\.s\.)\s+citizens?\s+only\b|"
    r"\bmust\s+be\s+(a\s+)?u\.s\.\s+citizen\b|"
    r"\bu\.s\.\s+citizenship\s+is\s+required\b",
    re.I,
)
NO_SPONSORSHIP_PATTERN = re.compile(
    r"\b(unable|not able)\s+to\s+provide\s+(visa\s+)?sponsorship\b|"
    r"\bdoes\s+not\s+offer\s+sponsorship\b|"
    r"\bwithout\s+sponsorship\b|"
    r"\bno\s+visa\s+sponsorship\s+is\s+available\b",
    re.I,
)
HIGH_EXPERIENCE_PATTERN = re.compile(r"\b(?:minimum|required|requires?|must have)?\s*([5-9]|1[0-9])\+?\s+years?\b", re.I)
US_LOCATION_TERMS = {
    "remote",
    "united states",
    "usa",
    "u.s.",
    "us",
    "new york",
    "ny",
    "california",
    "ca",
    "texas",
    "tx",
    "illinois",
    "il",
    "washington",
    "wa",
    "massachusetts",
    "ma",
    "florida",
    "fl",
    "georgia",
    "ga",
    "virginia",
    "va",
    "north carolina",
    "nc",
    "colorado",
    "co",
    "chicago",
    "new york city",
    "san francisco",
    "seattle",
    "boston",
    "austin",
    "atlanta",
}
NON_US_LOCATION_PATTERN = re.compile(r"\b(london|united kingdom|uk|canada|toronto|vancouver|india|singapore|germany)\b", re.I)


@dataclass(frozen=True, slots=True)
class FilterResult:
    allowed: bool
    reason: str | None = None


def apply_hard_filters(
    job: Job,
    accepted_families: set[str],
    allow_security_clearance: bool = False,
    requires_visa_sponsorship: bool = True,
) -> FilterResult:
    text = f"{job.title}\n{job.description}"
    if job.job_family.value not in accepted_families:
        return FilterResult(False, "ROLE_OUTSIDE_TARGET_FAMILIES")
    if _location_ineligible(job.location):
        return FilterResult(False, "LOCATION_INELIGIBLE")
    if SENIORITY_PATTERN.search(job.title):
        return FilterResult(False, "SENIORITY_TOO_HIGH")
    if _requires_high_experience(job.description):
        return FilterResult(False, "EXPERIENCE_REQUIREMENT_TOO_HIGH")
    if US_CITIZEN_PATTERN.search(text):
        return FilterResult(False, "US_CITIZEN_ONLY")
    if requires_visa_sponsorship and NO_SPONSORSHIP_PATTERN.search(text):
        return FilterResult(False, "NO_VISA_SPONSORSHIP")
    if not allow_security_clearance and CLEARANCE_PATTERN.search(text):
        return FilterResult(False, "INCOMPATIBLE_SECURITY_CLEARANCE")
    if job.employment_type and job.employment_type.upper() not in {"FULL_TIME", "FULL-TIME", "PERMANENT"}:
        return FilterResult(False, "INCOMPATIBLE_EMPLOYMENT_TYPE")
    return FilterResult(True)


def _requires_high_experience(description: str) -> bool:
    required_text = _required_section(description)
    for match in HIGH_EXPERIENCE_PATTERN.finditer(required_text):
        start = max(0, match.start() - 4)
        prefix = required_text[start : match.start()]
        if "-" in prefix:
            continue
        return True
    return False


def _required_section(description: str) -> str:
    lower = description.lower()
    preferred_index = min([idx for idx in [lower.find("preferred:"), lower.find("preferred qualifications:")] if idx >= 0] or [len(description)])
    return description[:preferred_index]


def _location_ineligible(location: str | None) -> bool:
    normalized = " ".join((location or "").lower().replace(",", " ").split())
    if not normalized:
        return False
    if any(term in normalized for term in US_LOCATION_TERMS):
        return False
    return bool(NON_US_LOCATION_PATTERN.search(normalized))
