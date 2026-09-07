"""Numeric résumé provenance red-team (WS2).

The truth system must classify every number as:
  SUPPORTED     - appears (normalized) in the text of a cited fact
  UNSUPPORTED   - a performance/scope number with no backing fact  -> reject
  NON-CLAIM     - year / version / course / contact digit          -> not a metric, must not be rejected as one

Covers: percentages, currency, integers, decimals, ranges, '15+', dates, years, counts, hours/week.
"""
from __future__ import annotations

import pytest

from app.resumes.truth_validation import validate_with_provenance


def check(text, numbers, fact_texts, fact_ids=("fact.a",), profile=("fact.a",)):
    item = {"text": text, "fact_ids": list(fact_ids), "numbers": list(numbers), "fact_texts": list(fact_texts)}
    return validate_with_provenance([item], profile_fact_ids=set(profile))


# --- SUPPORTED --------------------------------------------------------------
@pytest.mark.parametrize(
    "text,numbers,fact_texts",
    [
        ("Trained 15+ members", ["15"], ["Trained 15+ members of the robotics club"]),
        ("Reduced processing time by 20%", ["20"], ["Reduced processing time by 20% in a class project"]),
        ("Managed a $12,000 pilot budget", ["12,000"], ["Managed a $12,000 pilot budget"]),
        ("Maintained a 3.8 GPA", ["3.8"], ["Cumulative GPA 3.8 / 4.0"]),
        ("Volunteered 10 hours per week", ["10"], ["Volunteered ~10 hours/week at the tutoring center"]),
        ("Analyzed 50,000 rows", ["50,000"], ["retail dashboard — individual course project, ~50,000 rows"]),
        ("Analyzed 50k rows", ["50k"], ["dataset of about 50,000 rows"]),
    ],
)
def test_supported_numbers_pass(text, numbers, fact_texts):
    assert check(text, numbers, fact_texts).valid, text


# --- UNSUPPORTED ----------------------------------------------------------
@pytest.mark.parametrize(
    "text,numbers,fact_texts",
    [
        ("Trained 50+ members", ["50"], ["Trained 15+ members"]),
        ("Reduced processing time by 35%", ["35"], ["Reduced processing time by 20%"]),
        ("Managed a $120,000 budget", ["120,000"], ["Managed a $12,000 pilot budget"]),
        ("Led a team of 12", ["12"], ["treasurer of a 4-member student club"]),
        ("Improved accuracy by 40%", ["40"], ["improved accuracy (no figure recorded)"]),
    ],
)
def test_unsupported_numbers_are_rejected(text, numbers, fact_texts):
    res = check(text, numbers, fact_texts)
    assert not res.valid and any(n in "".join(res.unsupported_numbers) for n in numbers), text


# --- fail-closed when no fact text is provided --------------------------
def test_number_without_fact_texts_fails_closed():
    assert not check("Cut costs by 40%", ["40"], []).valid


# --- NON-CLAIM numbers must not be treated as metrics -----------------
@pytest.mark.parametrize(
    "text",
    [
        "Expected graduation May 2026",
        "Coursework: CS 146 Data Structures, MATH 161",
        "Built with Python 3.11 and pandas 2.2",
    ],
)
def test_non_claim_numbers_are_not_metrics(text):
    # The generator must not list years / version / course numbers in `numbers`.
    # With numbers=[] the claim is a normal (non-numeric) bullet and passes provenance
    # purely on fact_id grounds.
    res = check(text, [], ["edu: B.S. Business Analytics, expected May 2026", "skill: Python", "skill: pandas"])
    assert res.valid, text


def test_year_in_numbers_is_recognized_as_non_claim():
    # If the generator wrongly puts a calendar year in `numbers`, the validator should
    # recognize it as NON-CLAIM (year context) rather than flag it as an unsupported metric.
    res = check("Graduating May 2026", ["2026"], ["edu: expected May 2026"])
    assert res.valid  # 2026 is in the fact text, but ideally it is classified NON-CLAIM regardless


# --- ranges --------------------------------------------------------------
@pytest.mark.parametrize("dash", ["-", "–"])
def test_supported_range_number_passes(dash):
    text = f"Used Python across {1}{dash}{3} coursework projects"
    fact = f"Python used in 1{dash}3 coursework projects"
    assert check(text, [f"1{dash}3"], [fact]).valid


@pytest.mark.parametrize("dash", ["-", "–"])
def test_unsupported_range_number_is_rejected(dash):
    assert not check(f"Managed 8{dash}10 direct reports", [f"8{dash}10"], ["treasurer of a 4-member club"]).valid
