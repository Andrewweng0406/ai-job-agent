"""Discovery precision characterization — the first real run (OpenAI Ashby, 750 jobs) marked
490 applications ELIGIBLE, but the eligible set is dominated by senior IC / research roles
("Research Engineer", "Software Engineer, RL Training Infra", "Researcher, Robustness & Safety").

The deterministic filters only catch explicit "Senior" titles and explicit "N+ years" text.
Roles that phrase seniority softly ("deep experience", "track record of shipping", "PhD or
equivalent") pass. Per the PRIMARY PRINCIPLE this is "keep unless clearly disqualified", but a
real run would queue ~490 non-viable applications and burn the daily budget.

Not a safety issue (no fabrication, no submission). xfail = the precision gap.
"""
from __future__ import annotations

import pytest

from app.filtering.hard_filters import apply_hard_filters
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
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2 (discovery precision): soft seniority phrasing passes the deterministic filters; needs an LLM Stage-1 'realistically open to a graduating senior?' gate or a positive new-grad signal requirement")
def test_soft_seniority_phrasing_is_filtered_or_flagged(jd):
    res = apply_hard_filters(make_job(title="Research Engineer", description=jd), DATA)
    # ideally these are SKIPPED, or at least tagged for the LLM stage rather than straight-to-ELIGIBLE
    assert not res.allowed


def test_explicit_seniority_still_caught():
    assert not apply_hard_filters(make_job(title="Senior Research Engineer", description="x"), DATA).allowed
    assert not apply_hard_filters(
        make_job(title="Research Engineer", description="Requirements: 8+ years of experience."), DATA
    ).allowed


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2-5 (carried): title classifier is keyword-only; 'Research Engineer' / 'ML Framework Engineer' map into an accepted family with no new-grad signal")
def test_family_classifier_requires_a_newgrad_signal_for_broad_titles():
    from app.matching.taxonomy import RoleTaxonomy

    taxo = RoleTaxonomy({"TECHNICAL": {"persona": "TECHNICAL",
                                       "title_keywords": ["software engineer", "data engineer"]}})
    fam = taxo.classify_title("Software Engineer, RL Training Infrastructure")
    assert fam.value == "UNKNOWN", "a broad senior-leaning SWE title should not auto-classify without a new-grad marker"
