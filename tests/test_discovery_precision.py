"""Discovery precision — the first real run (OpenAI Ashby, 750 jobs) marked ~490 applications
ELIGIBLE, dominated by senior IC / research roles. Two deterministic fixes landed:

1. `RoleTaxonomy.classify_title` is two-tier: generic base titles ("software engineer",
   "data scientist", ...) classify into a family ONLY when a new-grad signal is present in the
   title or JD; otherwise UNKNOWN. `apply_hard_filters` rejects UNKNOWN outright.
2. `apply_hard_filters` rejects soft-seniority phrasing ("deep experience", "proven track
   record", "PhD or equivalent", "mentored engineers", ...) in the requirements region, unless
   the posting also carries a new-grad signal.

Not a safety issue (no fabrication, no submission) — a funnel-quality / cost issue.
"""
from __future__ import annotations

import pytest

from app.filtering.hard_filters import apply_hard_filters
from app.matching.taxonomy import RoleTaxonomy, is_new_grad_signal
from tests.adv_helpers import DATA, make_job

TECH = {"DATA_ANALYTICS", "TECHNICAL", "PRODUCT_PM", "BUSINESS_SYSTEMS", "FINANCE"}


SOFT_SENIOR_JDS = [
    # phrasing seen on real OpenAI / frontier-lab postings
    "You have deep experience designing and shipping large-scale ML training infrastructure.",
    "Proven track record of leading complex technical projects end to end.",
    "PhD in Computer Science or equivalent practical experience.",
    "You have shipped production systems used by millions and mentored other engineers.",
    "Significant industry experience building distributed systems at scale.",
]


@pytest.mark.parametrize("jd", SOFT_SENIOR_JDS)
def test_soft_seniority_phrasing_is_filtered(jd):
    res = apply_hard_filters(make_job(title="Data Analyst", description=jd), DATA)
    assert not res.allowed
    assert res.reason in {"SENIORITY_TOO_HIGH", "EXPERIENCE_REQUIREMENT_TOO_HIGH"}


def test_soft_seniority_phrasing_is_kept_when_the_posting_is_explicitly_new_grad():
    jd = ("New grad software engineer, class of 2026. You will be mentored by senior engineers "
          "and grow deep experience over time.")
    res = apply_hard_filters(make_job(title="Data Analyst", description=jd), DATA)
    assert res.allowed  # a new-grad signal overrides the soft-seniority phrases


def test_explicit_seniority_still_caught():
    assert not apply_hard_filters(make_job(title="Senior Research Engineer", description="x"), DATA).allowed
    assert not apply_hard_filters(
        make_job(title="Data Analyst", description="Requirements: 8+ years of experience."), DATA
    ).allowed


# --------------------------------------------------------------- two-tier classifier
def _taxo():
    return RoleTaxonomy({
        "TECHNICAL": {
            "persona": "TECHNICAL",
            "title_keywords": ["new grad software engineer", "junior software engineer"],
            "base_title_keywords": ["software engineer", "data engineer"],
        },
    })


def test_broad_title_without_a_newgrad_signal_is_unknown():
    fam = _taxo().classify_title("Software Engineer, RL Training Infrastructure")
    assert fam.value == "UNKNOWN"


def test_broad_title_with_a_newgrad_signal_in_the_title_classifies():
    fam = _taxo().classify_title("Software Engineer, New Grad (2026 Start)")
    assert fam.value == "TECHNICAL"


def test_broad_title_with_a_newgrad_signal_in_the_description_classifies():
    fam = _taxo().classify_title(
        "Software Engineer, Payments",
        description="This is an entry-level role for a graduating senior. 0-2 years experience.",
    )
    assert fam.value == "TECHNICAL"


def test_explicit_junior_title_classifies_without_any_signal():
    assert _taxo().classify_title("Junior Software Engineer").value == "TECHNICAL"


@pytest.mark.parametrize("text,expected", [
    ("New Grad Software Engineer", True),
    ("New College Grad, 2026", True),
    ("Early Career Analyst Program", True),
    ("University Graduate - Data", True),
    ("Recent graduate welcome", True),
    ("class of 2027", True),
    ("Staff Software Engineer", False),
    ("Senior Data Scientist with deep experience", False),
    ("We value grit", False),
])
def test_new_grad_signal_detector(text, expected):
    assert is_new_grad_signal(text) is expected
