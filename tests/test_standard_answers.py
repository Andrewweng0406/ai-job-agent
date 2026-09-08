"""Standard-answers resolution + the essay/must-queue question classifiers."""
from __future__ import annotations

import pytest

from app.applications.standard_answers import (
    StandardAnswers, is_essay_question, is_must_queue_question,
)

RULES = {
    "answers": {
        "work_authorized_us": "Yes",
        "requires_sponsorship_now_or_future": "Yes",
        "visa_now": "No",
        "country_of_residence": "United States",
        "willing_to_work_onsite": "Yes",
        "salary_expectation": "Open / negotiable",
        "how_did_you_hear": "LinkedIn",
        "currently_employed_here": "I have never worked here",
        "gender": "Decline to self-identify",
    },
    "match": [
        {"key": "work_authorized_us", "phrases": ["authorized to work"]},
        {"key": "visa_now", "phrases": ["do you now require"]},
        {"key": "requires_sponsorship_now_or_future", "phrases": ["now or in the future require", "require visa sponsorship"]},
        {"key": "country_of_residence", "phrases": ["country of residence", "country in which you are located"]},
        {"key": "willing_to_work_onsite", "phrases": ["willing to work from the office", "open to working in our office"]},
        {"key": "salary_expectation", "phrases": ["salary expectation"]},
        {"key": "how_did_you_hear", "phrases": ["how did you hear"]},
        {"key": "currently_employed_here", "phrases": ["ever worked for", "worked at or consulted for"]},
        {"key": "gender", "phrases": ["gender identity"]},
    ],
}


@pytest.fixture
def sa(tmp_path):
    import json
    p = tmp_path / "std.yaml"
    # load_yaml handles JSON too (superset); keep it simple
    p.write_text(json.dumps(RULES))
    return StandardAnswers.from_yaml(p)


@pytest.mark.parametrize("label,options,expected", [
    ("Are you legally authorized to work in the United States?", ["Yes", "No"], "Yes"),
    ("Do you now require sponsorship?", ["Yes", "No"], "No"),
    ("Will you now or in the future require visa sponsorship?", ["Yes", "No"], "Yes"),
    ("Please choose the country in which you are located.", None, "United States"),
    ("Are you willing to work from the office(s) listed?", ["Yes", "No"], "Yes"),
    ("Our team is in office 4 days/week. Are you open to working in our office?", ["Yes", "No"], "Yes"),
    ("What are your salary expectations?", None, "Open / negotiable"),
    ("How did you hear about us?", None, "LinkedIn"),
    ("What is your gender identity?", ["Male", "Female", "Decline to self-identify"], "Decline to self-identify"),
    ("Have you ever worked for Acme as an employee, intern or contractor?",
     ["I currently work at Acme", "I have never worked at Acme", "I previously worked at Acme"],
     "I have never worked at Acme"),
])
def test_resolution(sa, label, options, expected):
    assert sa.resolve(label, options) == expected


def test_unknown_question_returns_none(sa):
    assert sa.resolve("Describe your favourite algorithm", None) is None
    assert sa.resolve("What is your dog's name?", ["Rex", "Fido"]) is None


def test_the_more_specific_visa_now_rule_wins_over_the_generic(sa):
    # 'do you now require' must resolve to visa_now=No, not the future-sponsorship Yes
    assert sa.resolve("Do you now require immigration sponsorship?", ["Yes", "No"]) == "No"


@pytest.mark.parametrize("label", [
    "Why do you want to work at Stripe?",
    "Why are you interested in this role?",
    "What excites you about joining our team?",
    "Tell us why you'd be a great fit.",
])
def test_essay_questions_detected(label):
    assert is_essay_question(label)
    assert not is_must_queue_question(label)


@pytest.mark.parametrize("label", [
    "Describe a project you are proud of.",
    "Tell us about a time you overcame a challenge.",
    "Please provide two references.",
    "Link to your GitHub or portfolio.",
    "Anything else you'd like us to know?",
])
def test_must_queue_questions_detected(label):
    assert is_must_queue_question(label)


@pytest.mark.parametrize("label", ["First name", "Country", "Email address", "Start date"])
def test_plain_fields_are_neither(label):
    assert not is_essay_question(label)
    assert not is_must_queue_question(label)
