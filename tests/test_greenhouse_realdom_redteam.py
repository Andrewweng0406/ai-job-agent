"""Greenhouse real-DOM field-extraction red team (Round 3.1 WS6/WS7/WS14).

Drives HtmlFormFieldExtractor + the form engine against a representative Greenhouse hosted
application form (tests/fixtures/ats_forms/greenhouse_application.html — a hand-built fixture
shaped like the real DOM, NOT a live capture).

Passing tests = behavior that must hold. xfail(strict=False) = a real extraction bug
(CLAUDE_REVIEW P1-26 / P2-16 / P2-17).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.applications.form_engine import resolve_form_field
from app.applications.html_form_extractor import HtmlFormFieldExtractor
from app.resumes.profile import CandidateFact, CandidateProfile

FIXTURE = Path(__file__).parent / "fixtures" / "ats_forms" / "greenhouse_application.html"
HTML = FIXTURE.read_text()


def _fields():
    return HtmlFormFieldExtractor().extract(HTML, "greenhouse")


def _by_label(fields, needle):
    return [f for f in fields if needle.lower() in f.label.lower()]


def _profile():
    return CandidateProfile(
        candidate_id="cand",
        schema_version=2,
        facts={
            "name.full": CandidateFact("name.full", "identity", "Jane Q Student", required=True),
            "contact.email": CandidateFact("contact.email", "contact", "jane@example.test", required=True),
            "contact.phone": CandidateFact("contact.phone", "contact", "+1 555 010 2222", required=True),
        },
        application_answers={
            "work_authorized_us": "Yes",
            "requires_sponsorship_now_or_future": "Yes",
        },
    )


# --- radio group coalescing (P2-13, fixed) --------------------------------
def test_yes_no_radio_group_is_one_select_not_two_bools():
    fields = _fields()
    spon = _by_label(fields, "require sponsorship for employment visa")
    assert len(spon) == 1, f"sponsorship question must be ONE field, got {len(spon)}"
    assert spon[0].kind.value == "select"
    assert set(o.lower() for o in spon[0].options) >= {"yes", "no"}


def test_authorized_radio_group_is_one_field():
    assert len(_by_label(_fields(), "legally authorized to work")) == 1


# --- legend / label capture (P2-14, fixed) ------------------------------
def test_fieldset_legend_becomes_the_question_label():
    spon = _by_label(_fields(), "require sponsorship")[0]
    assert "sponsorship" in spon.label.lower() and "future" in spon.label.lower()


# --- file inputs -------------------------------------------------------
def test_resume_file_input_is_found_and_required():
    resume = _by_label(_fields(), "resume")
    assert resume and resume[0].kind.value == "file" and resume[0].required is True
    cover = _by_label(_fields(), "cover letter")
    assert cover and cover[0].required is False


# --- required detection via aria-required / '*' -----------------------
def test_required_markers_are_detected():
    fields = _fields()
    assert _by_label(fields, "first name")[0].required is True
    assert _by_label(fields, "phone")[0].required is False
    assert _by_label(fields, "desired annual compensation")[0].required is True


# --- EEO fields resolve to decline ----------------------------------
@pytest.mark.parametrize("needle", ["gender", "race", "veteran", "disability"])
def test_eeo_fields_are_never_answered_with_a_real_demographic_value(needle):
    """Safety invariant: an EEO field is either declined or HUMAN_REQUIRED — never a real value."""
    field = _by_label(_fields(), needle)[0]
    res = resolve_form_field(field, _profile(), "/tmp/r.pdf")
    if res.status.value == "FILLED":
        assert any(w in (res.value or "").lower() for w in ("decline", "wish", "want", "prefer not"))
    else:
        assert res.status.value in {"HUMAN_REQUIRED", "SKIPPED"}


@pytest.mark.parametrize("needle", ["gender", "race", "veteran", "disability"])
def test_eeo_fields_auto_decline_against_real_option_wording(needle):
    field = _by_label(_fields(), needle)[0]
    res = resolve_form_field(field, _profile(), "/tmp/r.pdf")
    assert res.status.value == "FILLED"
    assert any(w in (res.value or "").lower() for w in ("decline", "wish", "want", "prefer not"))


# --- known identity fields resolve from profile -------------------
def test_identity_fields_resolve_from_profile():
    fields = _fields()
    first = resolve_form_field(_by_label(fields, "first name")[0], _profile(), "/tmp/r.pdf")
    email = resolve_form_field(_by_label(fields, "email")[0], _profile(), "/tmp/r.pdf")
    assert first.status.value == "FILLED" and first.value == "Jane"
    assert email.status.value == "FILLED" and email.value == "jane@example.test"


# --- legal questions never auto-answered with an invented value --
@pytest.mark.parametrize("needle", ["legally authorized to work", "require sponsorship for employment visa"])
def test_legal_questions_are_safe(needle):
    field = _by_label(_fields(), needle)[0]
    res = resolve_form_field(field, _profile(), "/tmp/r.pdf")
    if res.status.value == "FILLED":
        assert res.value in {"Yes", "No"}  # only from the answer bank
        assert res.legal_sensitive is True
    else:
        assert res.status.value == "HUMAN_REQUIRED"


# --- unknown custom questions -> HUMAN_REQUIRED --------------------
@pytest.mark.parametrize("needle", ["desired annual compensation", "certify that the information"])
def test_unknown_required_custom_question_is_human_required(needle):
    field = _by_label(_fields(), needle)[0]
    res = resolve_form_field(field, _profile(), "/tmp/r.pdf")
    assert res.status.value == "HUMAN_REQUIRED"


# --- P1-26: honeypot / hidden field must NOT be extracted --------
def test_honeypot_field_is_excluded():
    fields = _fields()
    # the honeypot input name is job_application[hp_email]; it must not appear as a fillable field
    hp = [f for f in fields if "hp_email" in f.selector or f.label.strip().lower() in {"", "no", "yes"}]
    assert hp == [], f"honeypot / bleed-labeled field leaked into extraction: {[(f.label, f.selector) for f in hp]}"


# --- aria-labelledby: works when the target precedes the input (positional fallback) ---
def test_aria_labelledby_question_text_is_captured_when_label_precedes_input():
    textareas = [f for f in _fields() if f.kind.value == "long_text"]
    assert textareas, "the long-text custom question should be extracted"
    assert "project" in textareas[0].label.lower(), f"label was {textareas[0].label!r}"


def test_aria_labelledby_resolved_by_id_not_only_position():
    html = (
        "<form><input id='x' name='q' aria-labelledby='lbl' required>"
        "<span id='lbl'>What is your greatest weakness?</span></form>"
    )
    fields = HtmlFormFieldExtractor().extract(html, "greenhouse")
    assert fields and "weakness" in fields[0].label.lower()


# --- P2-17: no field may carry a label bled from the previous control --
def test_no_field_has_a_bled_or_degenerate_label():
    bad = [f for f in _fields() if f.label.strip() in {"", "*", "Yes", "No"}]
    assert bad == [], f"degenerate labels: {[f.label for f in bad]}"


# --- field count sanity: the real question set is represented once --
def test_logical_questions_appear_once_each():
    fields = _fields()
    for needle in [
        "first name", "last name", "email", "resume",
        "require sponsorship for employment visa", "legally authorized to work",
        "how did you hear", "desired annual compensation",
    ]:
        assert len(_by_label(fields, needle)) == 1, f"{needle!r} appears {len(_by_label(fields, needle))} times"
