"""Sponsorship / work-authorization adversarial corpus (WS3).

The candidate is an international student who WILL require future sponsorship.
- Hard negatives  -> must be filtered (reason NO_VISA_SPONSORSHIP / US_CITIZEN_ONLY / EXPORT_CONTROL_RESTRICTED)
- Ambiguous / positive -> must be KEPT (PRIMARY PRINCIPLE: don't drop unless clearly disqualified)
- Distinct legal concepts must NOT be collapsed into one rule.

The rules should stay conservative: hard negatives are filtered, while ambiguous or positive
sponsorship language is preserved for downstream handling.
"""
from __future__ import annotations

import pytest

from app.filtering.hard_filters import apply_hard_filters
from tests.adv_helpers import DATA, make_job


def r(desc: str):
    return apply_hard_filters(make_job(description=desc), DATA)


# --- hard negatives that ALREADY work -------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "must be authorized to work in the United States indefinitely without sponsorship",
        "this position is not eligible for visa sponsorship",
        "we are unable to provide visa sponsorship for this role",
        "no visa sponsorship is available",
        "sponsorship is not available for this position",
    ],
)
def test_hard_negative_sponsorship_is_filtered(text):
    res = r(text)
    assert not res.allowed and res.reason == "NO_VISA_SPONSORSHIP", text


@pytest.mark.parametrize(
    "text",
    [
        "we are unable to sponsor employment visas",
        "no sponsorship is available for this position",
        "we cannot provide current or future sponsorship",
        "the company does not sponsor applicants for work visas",
        "candidates must be able to work in the US on a permanent basis without employer sponsorship",
        "we are not in a position to offer immigration sponsorship",
    ],
)
def test_hard_negative_sponsorship_variants_are_filtered(text):
    res = r(text)
    assert not res.allowed and res.reason == "NO_VISA_SPONSORSHIP", text


# --- ambiguous / positive -> KEPT ---------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "sponsorship may be available for exceptional candidates",
        "sponsorship considered on a case-by-case basis",
        "OPT candidates are welcome to apply",
        "international graduates may apply",
        "candidates requiring sponsorship will be considered",
        "visa sponsorship is available for this role",
        "we are happy to sponsor qualified candidates",
    ],
)
def test_ambiguous_or_positive_sponsorship_is_kept(text):
    assert r(text).allowed, text


# --- citizenship: 'preferred' != 'required' ----------------------------
def test_citizenship_preferred_is_kept():
    assert r("U.S. citizenship preferred.").allowed


@pytest.mark.parametrize(
    "text",
    [
        "U.S. citizens only.",
        "Must be a U.S. citizen.",
        "U.S. citizenship is required for this position.",
    ],
)
def test_citizenship_required_forms_that_work(text):
    res = r(text)
    assert not res.allowed and res.reason == "US_CITIZEN_ONLY", text


@pytest.mark.parametrize(
    "text",
    [
        "U.S. citizenship required.",                       # no 'is'
        "Requires US citizenship.",
        "Must be a U.S. citizen or permanent resident.",
        "Applicants must have permanent residency.",
        "Position open to U.S. citizens and green card holders only.",
    ],
)
def test_citizenship_required_variants_are_filtered(text):
    res = r(text)
    assert not res.allowed and res.reason == "US_CITIZEN_ONLY", text


# --- concepts must stay distinct (not collapsed) ----------------------
def test_distinct_legal_concepts_have_distinct_reasons():
    itar = r("Due to ITAR, applicants must be a U.S. person.")
    clearance = r("Active Secret clearance required.")
    citizen = r("Must be a U.S. citizen.")
    assert itar.reason == "EXPORT_CONTROL_RESTRICTED"
    assert clearance.reason == "INCOMPATIBLE_SECURITY_CLEARANCE"
    assert citizen.reason == "US_CITIZEN_ONLY"
    # three different disqualifiers, three different reason codes — never one merged rule
    assert len({itar.reason, clearance.reason, citizen.reason}) == 3
