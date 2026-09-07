"""Form-engine red team (Round 3 WS5).

Attacks label classification + value resolution. The safety-critical rule:
  a legal / work-authorization question with unfamiliar phrasing MUST become HUMAN_REQUIRED,
  never an auto-answer; an unknown required field MUST become HUMAN_REQUIRED;
  a value that is not a valid option for a SELECT MUST become HUMAN_REQUIRED (FORM_MAPPING).

xfail(strict=False) = current classifier gap (CLAUDE_REVIEW P1-22 / P1-23).
"""
from __future__ import annotations

import pytest

from app.applications.form_engine import InputKind, RawFormField, resolve_form_field
from app.applications.form_fields import FieldPolicy, classify_label
from app.resumes.profile import CandidateProfile


def _profile() -> CandidateProfile:
    # a profile with the two canonical legal answers present
    prof = CandidateProfile.__new__(CandidateProfile)
    prof.facts = {}
    prof.application_answers = {
        "work_authorized_us": "Yes",
        "requires_sponsorship_now_or_future": "Yes",
    }
    return prof


def _field(label, kind=InputKind.TEXT, required=True, options=None):
    return RawFormField(label=label, kind=kind, selector="sel", required=required, options=options or [])


# --- known-safe legal phrasings still work --------------------------------
@pytest.mark.parametrize(
    "label",
    [
        "Are you legally authorized to work in the U.S.?",
        "Will you now or in the future require sponsorship?",
        "Do you now or in the future require sponsorship for an employment visa?",
    ],
)
def test_known_legal_questions_resolve_from_answer_bank(label):
    res = resolve_form_field(_field(label), _profile(), "/tmp/r.pdf")
    assert res.status.value == "FILLED"
    assert res.legal_sensitive is True


# --- unfamiliar legal phrasing must NOT auto-answer ----------------------
@pytest.mark.parametrize(
    "label",
    [
        "Do you require employer support to maintain work authorization?",
        "Would you need the company to file any petition on your behalf, now or later?",
        "Is your ability to work in the US contingent on employer action?",
        "Do you understand we cannot offer visa sponsorship?",
    ],
)
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-22: novel work-auth phrasing is misrouted to a canonical answer instead of HUMAN_REQUIRED")
def test_unfamiliar_legal_phrasing_is_human_required(label):
    res = resolve_form_field(_field(label), _profile(), "/tmp/r.pdf")
    assert res.status.value == "HUMAN_REQUIRED", f"{label} -> {res.status.value}/{res.value}"


# --- "source" substring must not swallow free-text fields --------------
@pytest.mark.parametrize(
    "label",
    [
        "Describe your open source contributions",
        "What is the primary source of your analytics experience?",
        "Source code samples (URL)",
    ],
)
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-22: bare 'source' substring maps to the 'How did you hear' auto-answer")
def test_source_substring_does_not_autofill_company_website(label):
    res = resolve_form_field(_field(label, required=False), _profile(), "/tmp/r.pdf")
    assert res.value != "Company website"


# --- a canonical 'how did you hear' still auto-fills -------------------
def test_how_did_you_hear_autofills():
    res = resolve_form_field(_field("How did you hear about us?", required=False), _profile(), "/tmp/r.pdf")
    assert res.status.value == "FILLED" and res.value == "Company website"


# --- SELECT option mapping -------------------------------------------
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-23: resolved value is not checked against SELECT options")
def test_select_value_not_in_options_is_form_mapping_human_required():
    # visa-status select whose options can't represent 'Yes'
    res = resolve_form_field(
        _field("Will you now or in the future require sponsorship?", kind=InputKind.SELECT,
               options=["I do not require sponsorship", "I will require sponsorship at some point"]),
        _profile(), "/tmp/r.pdf",
    )
    # 'Yes' is not one of the options -> must not be silently FILLED with 'Yes'
    assert res.status.value in {"HUMAN_REQUIRED", "BLOCKED"} or res.value in res.__dict__.get("options", []) \
        or res.value in ["I do not require sponsorship", "I will require sponsorship at some point"]


# --- unknown required field -> HUMAN_REQUIRED (this already works) -----
@pytest.mark.parametrize(
    "label",
    [
        "Expected annual compensation?",
        "Target base salary?",
        "Are you willing to relocate?",
        "Have you worked for us before?",
        "Do you have relatives employed here?",
        "Why do you want to work here?",
    ],
)
def test_unknown_required_field_is_human_required(label):
    res = resolve_form_field(_field(label, required=True), _profile(), "/tmp/r.pdf")
    assert res.status.value == "HUMAN_REQUIRED", f"{label} -> {res.status.value}"


# --- citizenship question is HUMAN_REQUIRED (not auto) ---------------
def test_citizenship_question_is_human_required():
    res = resolve_form_field(_field("Are you a U.S. citizen?"), _profile(), "/tmp/r.pdf")
    assert res.status.value == "HUMAN_REQUIRED"


# --- EEO always declines --------------------------------------------
@pytest.mark.parametrize("label", ["Gender", "Race / Ethnicity", "Veteran status", "Disability status"])
def test_eeo_fields_decline(label):
    res = resolve_form_field(_field(label, required=False), _profile(), "/tmp/r.pdf")
    assert res.status.value == "FILLED" and "decline" in (res.value or "").lower()


# --- missing canonical answer -> HUMAN_REQUIRED ---------------------
def test_missing_answer_bank_entry_is_human_required():
    prof = CandidateProfile.__new__(CandidateProfile)
    prof.facts = {}
    prof.application_answers = {}  # nothing set
    res = resolve_form_field(_field("Will you now or in the future require sponsorship?"), prof, "/tmp/r.pdf")
    assert res.status.value == "HUMAN_REQUIRED"
