"""Guards added while scaling the company registry to 40 boards — real postings that
slipped into ELIGIBLE and should not have: internships, non-US locations, and
government/defense/intel roles that are citizenship/clearance-gated for a candidate
who needs visa sponsorship.
"""
from __future__ import annotations

import pytest

from app.filtering.hard_filters import apply_hard_filters
from tests.adv_helpers import DATA, make_job

FAMILIES = {"DATA_ANALYTICS", "TECHNICAL", "PRODUCT_PM", "BUSINESS_SYSTEMS", "FINANCE"}


@pytest.mark.parametrize("title", [
    "Software Engineering Intern (Summer 2027)",
    "Software Engineer Intern (Winter 2027)",
    "Data Science Internship",
    "Engineering Co-op",
])
def test_internships_are_rejected(title):
    res = apply_hard_filters(make_job(title=title, description="Great early career role."), FAMILIES)
    assert not res.allowed
    assert res.reason == "INCOMPATIBLE_EMPLOYMENT_TYPE"


def test_internal_in_title_is_not_treated_as_internship():
    res = apply_hard_filters(
        make_job(title="Data Analyst, Internal Tools", description="New grad friendly."), DATA
    )
    assert res.allowed


@pytest.mark.parametrize("location", [
    "Mexico City, Mexico",
    "Guadalajara, Mexico",
    "Amsterdam, Netherlands",
    "Tel Aviv, Israel",
    "Remote - LATAM",
    "Remote - EMEA",
])
def test_non_us_locations_are_rejected(location):
    res = apply_hard_filters(
        make_job(title="Data Analyst", description="New grad role.", location=location), DATA
    )
    assert not res.allowed
    assert res.reason == "LOCATION_INELIGIBLE"


@pytest.mark.parametrize("title", [
    "Software Engineer, New Grad - Defense",
    "Forward Deployed Software Engineer, New Grad - Intel, US Government",
    "Operations Analyst - US Government",
    "Product Designer, New Grad - US Government",
    "Software Engineer - Defense Applications",
    "Forward Deployed Software Engineer - UK Government",
])
def test_government_and_defense_titles_are_rejected(title):
    res = apply_hard_filters(make_job(title=title, description="New grad, US-based."), FAMILIES)
    assert not res.allowed
    assert res.reason == "INCOMPATIBLE_SECURITY_CLEARANCE"


def test_commercial_new_grad_swe_still_passes():
    res = apply_hard_filters(
        make_job(title="Software Engineer, New Grad", description="Join our commercial team. US-based.",
                 location="New York, NY"),
        FAMILIES,
    )
    assert res.allowed


def test_gov_reject_can_be_opted_into_for_a_citizen_persona():
    res = apply_hard_filters(
        make_job(title="Software Engineer, New Grad - Defense", description="x"),
        FAMILIES, allow_security_clearance=True,
    )
    assert res.allowed
