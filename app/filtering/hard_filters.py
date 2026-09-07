from __future__ import annotations

from dataclasses import dataclass
import re

from app.models.job import Job
from app.models.enums import JobFamily


SENIORITY_PATTERN = re.compile(r"\b(senior|sr\.?|staff|principal|director|vp|executive|head of)\b", re.I)
CLEARANCE_PATTERN = re.compile(
    r"\b(active\s+)?(top secret|ts/sci|secret)\s+clearance\b|\bsecurity clearance\b|"
    r"\bability\s+to\s+obtain\s+(a\s+)?security\s+clearance\b",
    re.I,
)
US_CITIZEN_PATTERN = re.compile(
    r"\b(us|u\.s\.)\s+citizens?\s+only\b|"
    r"\bmust\s+be\s+(a\s+)?u\.s\.\s+citizen\b|"
    r"\bu\.?s\.?\s+citizenship\s+(is\s+)?required\b|"
    r"\brequires?\s+u\.?s\.?\s+citizenship\b|"
    r"\bmust\s+be\s+(a\s+)?u\.?s\.?\s+citizen\s+or\s+permanent\s+resident\b|"
    r"\bmust\s+have\s+permanent\s+residenc(y|e)\b|"
    r"\bpermanent\s+residenc(y|e)\s+required\b|"
    r"\b(u\.?s\.?\s+)?citizens?\s+and\s+green\s+card\s+holders?\s+only\b",
    re.I,
)
NO_SPONSORSHIP_PATTERN = re.compile(
    r"\b(unable|not able)\s+to\s+provide\s+(visa\s+)?sponsorship\b|"
    r"\bnot\s+able\s+to\s+sponsor\s+or\s+transfer\s+visas?\b|"
    r"\bdoes\s+not\s+offer\s+sponsorship\b|"
    r"\bmust\s+not\s+require\s+sponsorship\b|"
    r"\bwithout\s+sponsorship\b|"
    r"\bunrestricted\s+authorization\s+to\s+work\s+in\s+the\s+us\b|"
    r"\bwill\s+require\s+sponsorship\s+now\s+or\s+in\s+the\s+future\s+will\s+not\s+be\s+considered\b|"
    r"\bsponsorship\s+is\s+not\s+available\b|"
    r"\bnot\s+eligible\s+for\s+visa\s+sponsorship\b|"
    r"\bno\s+visa\s+sponsorship\s+is\s+available\b",
    re.I,
)
POSITIVE_SPONSORSHIP_PATTERN = re.compile(
    r"\bsponsorship\s+(is\s+)?(available|provided|offered)\b|\bwill\s+sponsor\b|\bhappy\s+to\s+sponsor\b",
    re.I,
)
HIGH_EXPERIENCE_PATTERN = re.compile(
    r"\b(?:minimum|required|requires?|must\s+have)(?:\s+of)?\s+([5-9]|1[0-9])\+?\s+years?"
    r"(?:\s+of)?\s+(?:professional\s+|relevant\s+)?experience\b|"
    r"\b([5-9]|1[0-9])\+?\s+years?(?:\s+of)?\s+(?:professional\s+|relevant\s+)?experience\b",
    re.I,
)
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
EXPORT_CONTROL_PATTERN = re.compile(r"\b(itar|export-controlled|export controlled|u\.s\.\s+persons?)\b", re.I)


@dataclass(frozen=True, slots=True)
class FilterResult:
    allowed: bool
    reason: str | None = None


def apply_hard_filters(
    job: Job,
    accepted_families: set[str],
    allow_security_clearance: bool = False,
    requires_visa_sponsorship: bool | None = True,
) -> FilterResult:
    text = f"{job.title}\n{job.description}"
    if job.job_family != JobFamily.UNKNOWN and job.job_family.value not in accepted_families:
        return FilterResult(False, "ROLE_OUTSIDE_TARGET_FAMILIES")
    if _location_ineligible(job.location):
        return FilterResult(False, "LOCATION_INELIGIBLE")
    if SENIORITY_PATTERN.search(job.title):
        return FilterResult(False, "SENIORITY_TOO_HIGH")
    if _requires_high_experience(job.description):
        return FilterResult(False, "EXPERIENCE_REQUIREMENT_TOO_HIGH")
    if US_CITIZEN_PATTERN.search(text):
        return FilterResult(False, "US_CITIZEN_ONLY")
    if EXPORT_CONTROL_PATTERN.search(text):
        return FilterResult(False, "EXPORT_CONTROL_RESTRICTED")
    has_negative_sponsorship = _has_negative_sponsorship(text)
    if requires_visa_sponsorship is None and has_negative_sponsorship:
        return FilterResult(False, "WORK_AUTHORIZATION_PROFILE_INCOMPLETE")
    if requires_visa_sponsorship and has_negative_sponsorship:
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
        if "-" in prefix or "–" in prefix or "—" in prefix or "to" in prefix:
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


def _has_negative_sponsorship(text: str) -> bool:
    if _has_positive_sponsorship(text) and not _has_explicit_negative_sponsorship(text):
        return False
    return _has_explicit_negative_sponsorship(text)


def _has_positive_sponsorship(text: str) -> bool:
    return bool(POSITIVE_SPONSORSHIP_PATTERN.search(text)) or bool(
        re.search(
            r"\bsponsorship\s+(may\s+be\s+available|considered|will\s+be\s+considered)\b|"
            r"\b(candidates\s+requiring\s+sponsorship\s+will\s+be\s+considered|opt\s+candidates\s+are\s+welcome)\b",
            text,
            re.I,
        )
    )


def _has_explicit_negative_sponsorship(text: str) -> bool:
    if NO_SPONSORSHIP_PATTERN.search(text):
        return True
    normalized = " ".join(text.lower().replace("-", " ").replace("/", " ").split())
    negative_window_patterns = [
        r"\b(unable|not able|cannot|can't)\s+(?:\w+\s+){0,5}(sponsor|provide|offer)\s+(?:\w+\s+){0,4}(sponsorship|visas?|work\s+visas?|employment\s+visas?)\b",
        r"\b(does\s+not|do\s+not|will\s+not)\s+(?:\w+\s+){0,5}(sponsor|provide|offer)\s+(?:\w+\s+){0,4}(sponsorship|visas?|work\s+visas?)\b",
        r"\bnot\s+in\s+a\s+position\s+to\s+offer\s+(immigration\s+)?sponsorship\b",
        r"\bno\s+(visa\s+)?sponsorship\s+is\s+available\b",
        r"\bwithout\s+(employer\s+)?sponsorship\b",
        r"\bpermanent\s+basis\s+without\s+(employer\s+)?sponsorship\b",
        r"\bmust\s+(not\s+require|be\s+able\s+to\s+work\s+.*without)\s+(employer\s+)?sponsorship\b",
        r"\bcurrent\s+or\s+future\s+sponsorship\b",
    ]
    if any(re.search(pattern, normalized, re.I) for pattern in negative_window_patterns):
        return True
    return False
