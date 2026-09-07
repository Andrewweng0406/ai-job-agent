"""Resume truthfulness red-team.

Tricky transforms an LLM tends to make, each of which must be REJECTED:
  1. "used Python for analysis"      -> "built production Python systems"
  2. hobby finance analysis          -> professional finance experience
  3. student leadership              -> people-management / hiring authority
  4. project work                    -> paid employment
  5. familiarity / basic use         -> expertise / deep experience
  6. real metric                     -> inflated metric
  7. cites a real fact_id            -> but the sentence overreaches what the fact supports

See docs/RESUME_TRUTH_SYSTEM.md. xfail = gap in the current validators (CLAUDE_REVIEW P1-5 / P1-12).
"""
from __future__ import annotations

import pytest

from app.resumes.truth_validation import (
    validate_claims_against_profile,
    validate_with_provenance,
)

PROFILE_FACTS = [
    "skill: Python — used for data analysis in coursework",
    "skill: SQL — familiar, basic SELECT/JOIN queries",
    "project: retail sales dashboard — individual course project, ~50k rows",
    "project: personal budgeting analysis — hobby, personal spreadsheet",
    "leadership: treasurer of a student club, 4 members, tracked dues",
    "experience: data analyst intern, campus office, summer 2025, 10 weeks",
]

INFLATIONS = [
    "Built and operated production Python systems serving millions of users.",
    "Delivered professional finance advisory and investment analysis for external clients.",
    "Managed a team of six engineers, including performance reviews and hiring decisions.",
    "Employed full-time as a Data Analyst; owned the retail analytics platform.",
    "Expert-level SQL engineer with years of query-optimization and warehouse tuning experience.",
    "Drove a 65% reduction in company-wide reporting costs across all business units.",
]


@pytest.mark.parametrize("claim", INFLATIONS)
def test_inflated_claims_are_rejected_by_profile_check(claim):
    r = validate_claims_against_profile([claim], PROFILE_FACTS)
    assert not r.valid, f"inflation slipped through: {claim}"
    assert claim in r.unsupported_claims


def test_legit_paraphrase_is_still_accepted():
    """Guardrail against over-blocking: a faithful paraphrase of a fact should pass."""
    claim = "Used Python and SQL to analyze coursework datasets."
    r = validate_claims_against_profile([claim], PROFILE_FACTS)
    if not r.valid:
        pytest.xfail("CLAUDE_REVIEW P1-5: token-overlap check also rejects faithful paraphrases")
    assert r.valid


@pytest.mark.parametrize(
    "item",
    [
        {"text": "Built production Python systems.", "fact_ids": ["skill.python"], "numbers": []},
        {"text": "Managed a team of 6 engineers and led hiring.", "fact_ids": ["leadership.club_treasurer"], "numbers": ["6"]},
        {"text": "Senior finance professional advising institutional clients.", "fact_ids": ["project.budgeting_hobby"], "numbers": []},
    ],
)
def test_real_fact_id_with_overreaching_text_is_rejected(item):
    r = validate_with_provenance([item], profile_fact_ids={"skill.python", "leadership.club_treasurer", "project.budgeting_hobby"})
    assert not r.valid, f"overreach with a valid fact_id slipped through: {item['text']}"


def test_fabricated_number_with_valid_fact_ids_is_flagged():
    item = {"text": "Analyzed 5,000,000 transactions.", "fact_ids": ["project.retail_dashboard"], "numbers": ["5,000,000"]}
    r = validate_with_provenance([item], profile_fact_ids={"project.retail_dashboard"})
    assert not r.valid
    assert "5,000,000" in r.unsupported_numbers


def test_legit_cited_number_is_accepted():
    """A number that appears in the text of a cited fact must NOT be flagged."""
    item = {
        "text": "Analyzed 50,000 transaction rows for a course project.",
        "fact_ids": ["project.retail_dashboard"],
        "numbers": ["50,000"],
        "fact_texts": ["project: retail sales dashboard — individual course project, ~50,000 rows"],
    }
    r = validate_with_provenance([item], profile_fact_ids={"project.retail_dashboard"})
    assert r.valid, "a metric supported by a cited fact should pass"


def test_uncited_claim_is_always_rejected():
    r = validate_with_provenance(
        [{"text": "Led company-wide analytics strategy.", "fact_ids": [], "numbers": []}],
        profile_fact_ids={"skill.python"},
    )
    assert not r.valid
    assert "Led company-wide analytics strategy." in r.unsupported_claims


def test_unknown_fact_id_is_always_rejected():
    r = validate_with_provenance(
        [{"text": "Shipped a recommender system.", "fact_ids": ["project.ghost"], "numbers": []}],
        profile_fact_ids={"skill.python"},
    )
    assert not r.valid
    assert "project.ghost" in r.unknown_fact_ids
