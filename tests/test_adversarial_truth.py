"""Adversarial truthfulness tests. See docs/RESUME_TRUTH_SYSTEM.md and docs/CLAUDE_REVIEW.md P1-5/P1-6."""
from __future__ import annotations

import pytest

from app.resumes.truth_validation import validate_claims_against_profile


# ADV-14: fabricated skill is caught ------------------------------------------
def test_adv14_unsupported_skill_is_flagged():
    r = validate_claims_against_profile(
        claims=["Python", "SQL", "AWS"],
        supported_facts=["Python", "SQL", "Tableau"],
    )
    assert not r.valid
    assert "AWS" in r.unsupported_claims


# P1-5: the stub cannot validate real sentence-form bullets -------------------
@pytest.mark.xfail(strict=False, reason="P1-5: exact string match rejects legitimately supported bullets")
def test_supported_sentence_bullet_is_accepted():
    # This bullet is fully supported by the facts, but is not a verbatim fact string.
    r = validate_claims_against_profile(
        claims=["Built Tableau dashboards on retail data using SQL."],
        supported_facts=[
            "skill:SQL", "skill:Tableau", "project:retail dashboard",
            "Built an interactive Tableau dashboard on retail transactions using SQL.",
        ],
    )
    assert r.valid


# ADV-15: omission of a required field must be detectable --------------------
@pytest.mark.xfail(strict=False, reason="RESUME_TRUTH_SYSTEM sec.4 step 6: no required-field omission check yet")
def test_adv15_missing_graduation_date_is_flagged():
    from app.resumes import truth_validation as tv

    check = getattr(tv, "check_required_fields", None)
    assert check is not None, "expected a required-field presence check"
    result = check(resume_sections={"education": "San Jose State University, B.S. Business Analytics"},
                   required_fact_ids=["edu.bs.school", "edu.bs.degree", "edu.bs.grad_date"])
    assert "edu.bs.grad_date" in result.missing


# ADV-16: unknown legal question must route to HUMAN_REQUIRED ----------------
@pytest.mark.xfail(strict=False, reason="RESUME_TRUTH_SYSTEM sec.6: no answer engine / legal-question guard yet")
def test_adv16_unknown_sponsorship_question_is_human_required():
    from app.resumes import truth_validation as tv

    answer_question = getattr(tv, "answer_application_question", None)
    assert answer_question is not None
    outcome = answer_question(
        question="If hired, describe in detail your current and future immigration status and any "
                 "restrictions on your ability to work.",
        answer_bank={"work_authorized_us": "Yes", "requires_sponsorship_now_or_future": "Yes"},
    )
    assert outcome.state.name == "HUMAN_REQUIRED"


# Provenance: unknown fact ids must never validate --------------------------
@pytest.mark.xfail(strict=False, reason="RESUME_TRUTH_SYSTEM sec.4 step 2: no fact_id provenance model yet")
def test_claim_citing_unknown_fact_id_is_rejected():
    from app.resumes import truth_validation as tv

    validate = getattr(tv, "validate_with_provenance", None)
    assert validate is not None
    r = validate(
        items=[{"text": "Led a team of 12 engineers.", "fact_ids": ["exp.does_not_exist"], "numbers": ["12"]}],
        profile_fact_ids={"edu.bs.school", "skill.sql"},
    )
    assert not r.valid
