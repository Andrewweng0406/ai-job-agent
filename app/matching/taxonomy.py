from __future__ import annotations

import re
from pathlib import Path

from app.models.enums import JobFamily
from app.utils.config import load_yaml


# A "new-grad signal" is explicit language that a posting targets graduating
# students / early-career candidates. Generic base titles (e.g. "software
# engineer") only classify into a family when one of these appears in the
# title or the job description.
NEW_GRAD_SIGNAL = re.compile(
    r"\b("
    r"new[\s-]?grad(uate)?s?|new college grad(uate)?s?|new-college-grad|"
    r"university\s+grad(uate)?|university\s+hire|campus\s+(hire|recruit\w*)|"
    r"recent\s+grad(uate)?s?|graduating\s+(senior|student)s?|"
    r"early[\s-]career|entry[\s-]level|"
    r"class\s+of\s+20\d{2}|20(2[5-9]|3\d)\s+(start|grad\w*|cohort)|"
    r"rotational\s+program|new\s+graduate\s+program|"
    r"0[-–\s]*to[-–\s]*2\s+years|0[-–]2\s+years|"
    r"final[\s-]year\s+student|currently\s+pursuing\s+(a\s+)?(bachelor|master)"
    r")\b",
    re.I,
)


# Boilerplate where a "new grad" mention actually EXCLUDES new-grad applicants
# (e.g. Stripe's "if you are an intern, new grad, or staff applicant, please do
# not apply using this link"). If any of these sit close to the signal match,
# the mention is not a genuine targeting signal.
_NEGATION_NEAR_SIGNAL = re.compile(
    r"do\s+not\s+apply|don'?t\s+apply|should\s+not\s+apply|please\s+visit|"
    r"not\s+eligible|this\s+is\s+not\s+a|is\s+not\s+intended\s+for|"
    r"separate\s+(job\s+)?post|different\s+(job\s+)?post|wrong\s+(link|posting)",
    re.I,
)


_SENIOR_TITLE_MARKER = re.compile(
    r"\b(senior|sr\.?|staff|principal|distinguished|"
    r"manager|director|vp|vice president|head of|chief)\b|"
    r"\b(engineer|scientist|analyst|developer|designer)\s+(iii|iv|v)\b|"
    r"\blevel\s*[3-9]\b|\bl[3-9]\b",
    re.I,
)


def is_new_grad_signal(text: str) -> bool:
    blob = text or ""
    for match in NEW_GRAD_SIGNAL.finditer(blob):
        window = blob[max(0, match.start() - 80): match.end() + 80]
        if not _NEGATION_NEAR_SIGNAL.search(window):
            return True
    return False


class RoleTaxonomy:
    def __init__(self, accepted_families: dict[str, dict[str, object]]) -> None:
        self.accepted_families = accepted_families

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RoleTaxonomy":
        data = load_yaml(path)
        return cls(data.get("accepted_job_families", {}))

    def accepted_family_names(self) -> set[str]:
        return set(self.accepted_families)

    def classify_title(self, title: str, description: str = "") -> JobFamily:
        normalized = " ".join(title.lower().split())

        # Tier 1: explicit early-career titles always classify.
        for family_name, config in self.accepted_families.items():
            for keyword in _keyword_list(config, "title_keywords"):
                if keyword in normalized:
                    return JobFamily(family_name)

        # A senior/lead marker in the TITLE is disqualifying — a JD's "early
        # career" blurb must not rescue a "Senior Data Scientist".
        if _SENIOR_TITLE_MARKER.search(normalized):
            return JobFamily.UNKNOWN

        # Tier 2: generic base titles classify only with a new-grad signal.
        if is_new_grad_signal(f"{title}\n{description}"):
            for family_name, config in self.accepted_families.items():
                for keyword in _keyword_list(config, "base_title_keywords"):
                    if keyword in normalized:
                        return JobFamily(family_name)

        return JobFamily.UNKNOWN


def _keyword_list(config: dict[str, object], key: str) -> list[str]:
    value = config.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).lower() for item in value]
