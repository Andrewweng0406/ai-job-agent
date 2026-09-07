"""Adversarial hard-filter tests. See docs/FAILURE_MODEL.md sec.7 and docs/CLAUDE_REVIEW.md.

Tests marked xfail(strict=False) document desired behavior that Phase 1 does not yet implement.
When Codex lands the fix, the test flips to XPASS -> promote it to a plain assertion.
"""
from __future__ import annotations

import pytest

from app.filtering.hard_filters import apply_hard_filters
from tests.adv_helpers import DATA, make_job


# ADV-01 -------------------------------------------------------------------------
def test_adv01_senior_title_is_skipped():
    r = apply_hard_filters(make_job(title="Senior Data Scientist", description="early career welcome"), DATA)
    assert not r.allowed
    assert r.reason == "SENIORITY_TOO_HIGH"


# ADV-02 -----------------------------------------------------------------------
def test_adv02_citizenship_preferred_is_allowed():
    r = apply_hard_filters(
        make_job(description="US citizenship preferred but not required."), DATA
    )
    assert r.allowed, "‘preferred’ must not be treated as a disqualifier"


# ADV-03 -----------------------------------------------------------------------
def test_adv03_must_be_us_citizen_is_skipped():
    r = apply_hard_filters(make_job(description="Applicants must be a U.S. citizen."), DATA)
    assert not r.allowed and r.reason == "US_CITIZEN_ONLY"


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P0-3/P1: 'US citizenship is required' phrasing not matched")
def test_adv03b_citizenship_is_required_phrasing_is_skipped():
    r = apply_hard_filters(make_job(description="U.S. citizenship is required for this position."), DATA)
    assert not r.allowed and r.reason == "US_CITIZEN_ONLY"


# ADV-04 -----------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P0-3: no NO_SPONSORSHIP_PATTERN yet")
@pytest.mark.parametrize(
    "text",
    [
        "We are unable to provide visa sponsorship for this role.",
        "This position does not offer sponsorship now or in the future.",
        "Candidates must be authorized to work in the U.S. without sponsorship.",
        "No visa sponsorship is available.",
    ],
)
def test_adv04_no_sponsorship_is_skipped(text):
    r = apply_hard_filters(make_job(description=text), DATA)
    assert not r.allowed and r.reason == "NO_VISA_SPONSORSHIP"


# ADV-05 -----------------------------------------------------------------------
def test_adv05_sponsorship_available_is_allowed():
    r = apply_hard_filters(
        make_job(description="Visa sponsorship is available for this role."), DATA
    )
    assert r.allowed


# ADV-06 -----------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-1: experience scan hits Preferred section / whole blob")
def test_adv06_years_only_in_preferred_section_is_allowed():
    desc = (
        "Requirements:\n- 0-2 years of experience\n- SQL, Excel\n\n"
        "Preferred:\n- 5+ years working with dashboards is a plus\n"
    )
    r = apply_hard_filters(make_job(description=desc), DATA)
    assert r.allowed


# ADV-07 -----------------------------------------------------------------------
def test_adv07_minimum_7_years_is_skipped():
    r = apply_hard_filters(
        make_job(description="Requirements: Minimum 7 years of professional experience."), DATA
    )
    assert not r.allowed and r.reason == "EXPERIENCE_REQUIREMENT_TOO_HIGH"


# ADV-08 -----------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-1: range '1-5 years' includes new grads, should not be dropped")
def test_adv08_year_range_including_newgrad_is_allowed():
    r = apply_hard_filters(make_job(description="1-5 years of experience with SQL."), DATA)
    assert r.allowed


# ADV-09 -----------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-2: bare word 'secret' matches clearance pattern")
@pytest.mark.parametrize(
    "text",
    [
        "You will help protect our trade secret formulas.",
        "Financial Analyst supporting the Victoria's Secret retail account.",
    ],
)
def test_adv09_secret_without_clearance_context_is_allowed(text):
    r = apply_hard_filters(make_job(description=text), DATA)
    assert r.allowed


# ADV-10 -----------------------------------------------------------------------
def test_adv10_tssci_clearance_required_is_skipped():
    r = apply_hard_filters(
        make_job(description="Active TS/SCI clearance required."), DATA
    )
    assert not r.allowed and r.reason == "INCOMPATIBLE_SECURITY_CLEARANCE"


# ADV-21 -----------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-7: no US-location filter")
def test_adv21_non_us_location_is_skipped():
    r = apply_hard_filters(make_job(location="London, United Kingdom"), DATA)
    assert not r.allowed and r.reason == "LOCATION_INELIGIBLE"


# ADV-22 -----------------------------------------------------------------------
def test_adv22_unknown_location_is_kept():
    r = apply_hard_filters(make_job(location=""), DATA)
    assert r.allowed, "unknown location must be kept per PRIMARY PRINCIPLE"


# Employment type -------------------------------------------------------------
def test_internship_employment_type_is_skipped():
    r = apply_hard_filters(make_job(employment_type="INTERNSHIP"), DATA)
    assert not r.allowed and r.reason == "INCOMPATIBLE_EMPLOYMENT_TYPE"
