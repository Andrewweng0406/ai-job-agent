"""Round 1.5 expanded adversarial hard-filter coverage.

Focus: experience ranges, ambiguous sponsorship phrasing, citizenship vs. work-authorization,
security-clearance / export-control variants.

xfail(strict=False) = desired behavior not yet implemented; each references a CLAUDE_REVIEW finding.
Plain asserts = behavior that must hold and currently does (regression guard).
"""
from __future__ import annotations

import pytest

from app.filtering.hard_filters import apply_hard_filters
from tests.adv_helpers import DATA, make_job


def result(desc: str, **kw):
    return apply_hard_filters(make_job(description=desc, **kw), DATA)


# ---------------------------------------------------------------------------
# Experience ranges — the low bound decides. A range that includes new grads is KEEP.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phrase",
    [
        "Requirements: 1-3 years of experience.",
        "Requirements: 0-2 years of experience.",
        "Requirements: up to 2 years of experience.",
        "Requirements: 2+ years of experience.",
        "Requirements: 3+ years of experience preferred.",
        "Requirements: 2 - 6 years of experience.",       # spaced ASCII hyphen (handled today)
    ],
)
def test_experience_ranges_that_include_newgrads_are_kept(phrase):
    assert result(phrase).allowed, phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "Requirements: 1–5 years of experience.",   # en dash
        "Requirements: 1—5 years of experience.",   # em dash
        "Requirements: 3 to 5 years of experience.",     # word 'to'
    ],
)
def test_experience_ranges_with_nonascii_or_word_separators_are_kept(phrase):
    assert result(phrase).allowed, phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "Requirements: Minimum 7 years of professional experience.",
        "Requirements: A minimum of 5 years of experience.",
        "Requirements: 8+ years of experience required.",
    ],
)
def test_clear_high_minimum_experience_is_skipped(phrase):
    r = result(phrase)
    assert not r.allowed and r.reason == "EXPERIENCE_REQUIREMENT_TOO_HIGH", phrase


def test_high_years_only_in_preferred_section_is_kept():
    assert result("Requirements: SQL, Python.\nPreferred: 6+ years of dashboarding.").allowed


# ---------------------------------------------------------------------------
# Sponsorship — negative phrasing disqualifies (candidate needs future sponsorship);
# positive / neutral phrasing does not.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phrase",
    [
        "We are unable to provide visa sponsorship for this role.",
        "This position does not offer sponsorship.",
        "No visa sponsorship is available.",
        "Candidates must be authorized to work in the U.S. without sponsorship.",
    ],
)
def test_explicit_no_sponsorship_is_skipped(phrase):
    r = result(phrase)
    assert not r.allowed and r.reason == "NO_VISA_SPONSORSHIP", phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "Applicants must not require sponsorship now or in the future.",
        "We are not able to sponsor or transfer visas at this time.",
        "Candidates must have unrestricted authorization to work in the US.",
        "Candidates who will require sponsorship now or in the future will not be considered.",
        "Sponsorship is not available for this position.",
        "This role is not eligible for visa sponsorship.",
    ],
)
def test_ambiguous_no_sponsorship_phrasings_are_skipped(phrase):
    r = result(phrase)
    assert not r.allowed and r.reason == "NO_VISA_SPONSORSHIP", phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "Visa sponsorship is available for this role.",
        "We are happy to sponsor qualified candidates.",
        "H-1B sponsorship provided for the right candidate.",
    ],
)
def test_positive_sponsorship_is_kept(phrase):
    assert result(phrase).allowed, phrase


# ---------------------------------------------------------------------------
# Citizenship vs. work authorization — distinct concepts.
#   "must be a citizen"      -> disqualified (candidate is not)
#   "must be work-authorized"-> KEEP (candidate is authorized via CPT/OPT)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phrase",
    [
        "Must be authorized to work in the United States.",
        "Applicants must have current U.S. work authorization.",
        "You must be legally eligible to work in the US.",
    ],
)
def test_plain_work_authorization_requirement_is_kept(phrase):
    assert result(phrase).allowed, phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "U.S. citizens only.",
        "Must be a U.S. citizen.",
        "U.S. citizenship is required for this position.",
        "Must be a U.S. citizen or lawful permanent resident.",
    ],
)
def test_citizenship_requirement_is_skipped(phrase):
    r = result(phrase)
    assert not r.allowed and r.reason == "US_CITIZEN_ONLY", phrase


def test_citizenship_preferred_is_kept():
    assert result("U.S. citizenship preferred but not required.").allowed


# ---------------------------------------------------------------------------
# Security clearance / export control variants.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phrase",
    [
        "Active TS/SCI clearance required.",
        "Must hold an active Secret clearance.",
        "Position requires a Top Secret clearance.",
        "Applicants must be able to obtain a security clearance.",
    ],
)
def test_clearance_requirements_are_skipped(phrase):
    r = result(phrase)
    assert not r.allowed and r.reason == "INCOMPATIBLE_SECURITY_CLEARANCE", phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "You will help protect our trade secret formulas.",
        "Financial Analyst supporting the Victoria's Secret retail account.",
        "We keep our roadmap secret until launch.",
    ],
)
def test_bare_word_secret_without_clearance_context_is_kept(phrase):
    assert result(phrase).allowed, phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "Due to ITAR, applicants must be U.S. Persons.",
        "This role requires access to export-controlled information; U.S. Person status required.",
    ],
)
def test_itar_us_person_requirement_is_skipped(phrase):
    r = result(phrase)
    assert not r.allowed and r.reason in {"US_CITIZEN_ONLY", "INCOMPATIBLE_SECURITY_CLEARANCE", "EXPORT_CONTROL_RESTRICTED"}, phrase


# ---------------------------------------------------------------------------
# Expired / closed posting handling at the state layer.
# ---------------------------------------------------------------------------
def test_state_machine_allows_close_from_every_pre_submit_state():
    from app.applications.state_machine import ALLOWED_TRANSITIONS
    from app.models.enums import ApplicationStatus

    for pre_submit in [
        ApplicationStatus.DISCOVERED,
        ApplicationStatus.QUEUED,
        ApplicationStatus.TAILORING,
        ApplicationStatus.READY,
        ApplicationStatus.APPLYING,
    ]:
        assert ApplicationStatus.CLOSED in ALLOWED_TRANSITIONS[pre_submit], pre_submit
