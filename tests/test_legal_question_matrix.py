"""Shared-ATS legal / work-authorization question matrix (autonomous red team).

`resolve_form_field` is shared by the Greenhouse/Lever/Ashby dry-run adapters. The invariant:
a legal, work-authorization, citizenship, or clearance question is NEVER auto-answered with an
invented value — it is FILLED only from an explicit answer-bank entry, otherwise HUMAN_REQUIRED.
Salary / relocation with no canonical answer -> HUMAN_REQUIRED.

This is the audit baseline for every future Lever/Ashby live run.
"""
from __future__ import annotations

import pytest

from app.applications.form_engine import InputKind, RawFormField, resolve_form_field
from app.resumes.profile import CandidateProfile

BANK = {
    "work_authorized_us": "Yes",
    "requires_sponsorship_now_or_future": "Yes",
    "willing_to_relocate": "Yes",
}


def _profile(bank=None):
    return CandidateProfile("c", 2, {}, dict(BANK if bank is None else bank))


def _f(label, kind=InputKind.TEXT, required=True, options=None):
    return RawFormField(label=label, kind=kind, selector="s", required=required, options=options or [])


def _resolve(label, **kw):
    return resolve_form_field(_f(label, **kw), _profile(), "/tmp/r.pdf")


ANSWER_BANK_VALUES = {"Yes", "No"}


# --------------------------------------------------------------------- sponsorship
@pytest.mark.parametrize(
    "label",
    [
        "Will you now or in the future require sponsorship for employment visa status?",
        "Do you now or in the future require sponsorship to work in the United States?",
        "Will you require visa sponsorship?",
    ],
)
def test_sponsorship_questions_only_from_answer_bank_or_human(label):
    r = _resolve(label)
    if r.status.value == "FILLED":
        assert r.value in ANSWER_BANK_VALUES and r.legal_sensitive is True
    else:
        assert r.status.value == "HUMAN_REQUIRED"


# --------------------------------------------------------------------- work authorization (distinct from sponsorship)
@pytest.mark.parametrize(
    "label",
    [
        "Are you legally authorized to work in the United States?",
        "Do you have current work authorization in the US?",
        "Are you authorized to work in the country where this role is based?",
        "Do you have unrestricted authorization to work in the United States?",
        "Will you require employer support to maintain work authorization?",  # really sponsorship
    ],
)
def test_work_authorization_questions_are_never_invented(label):
    r = _resolve(label)
    assert r.status.value in {"FILLED", "HUMAN_REQUIRED"}
    if r.status.value == "FILLED":
        assert r.value in ANSWER_BANK_VALUES, f"{label!r} auto-filled with {r.value!r}"


# --------------------------------------------------------------------- citizenship / permanent residency
@pytest.mark.parametrize(
    "label",
    [
        "Are you a U.S. citizen?",
        "Are you a U.S. citizen or permanent resident?",
        "Do you hold U.S. citizenship?",
        "Are you a green card holder?",
    ],
)
def test_citizenship_questions_are_human_required(label):
    # we have no canonical answer key for citizenship -> must not guess
    r = _resolve(label)
    assert r.status.value == "HUMAN_REQUIRED", f"{label!r} -> {r.status.value}/{r.value}"


# --------------------------------------------------------------------- clearance / export control
@pytest.mark.parametrize(
    "label",
    [
        "Do you currently hold an active security clearance?",
        "Are you able to obtain a U.S. security clearance?",
        "This role requires access to export-controlled information. Are you a U.S. Person?",
    ],
)
def test_clearance_questions_are_human_required(label):
    r = _resolve(label)
    assert r.status.value == "HUMAN_REQUIRED"


# --------------------------------------------------------------------- salary / relocation
@pytest.mark.parametrize(
    "label",
    [
        "What are your salary expectations?",
        "Desired base salary (USD)",
        "Expected total compensation",
    ],
)
def test_salary_questions_are_human_required(label):
    assert _resolve(label).status.value == "HUMAN_REQUIRED"


@pytest.mark.parametrize("label", ["Are you willing to relocate?", "Would you relocate for this role?"])
def test_relocation_resolves_from_answer_bank_or_human(label):
    r = _resolve(label, kind=InputKind.SELECT, options=["Yes", "No"])
    assert r.status.value in {"FILLED", "HUMAN_REQUIRED"}
    if r.status.value == "FILLED":
        assert r.value in {"Yes", "No"}


# --------------------------------------------------------------------- missing answer bank -> always human
@pytest.mark.parametrize(
    "label",
    [
        "Will you now or in the future require sponsorship?",
        "Are you legally authorized to work in the United States?",
    ],
)
def test_no_answer_bank_entry_forces_human_required(label):
    r = resolve_form_field(_f(label), _profile(bank={}), "/tmp/r.pdf")
    assert r.status.value == "HUMAN_REQUIRED"


# --------------------------------------------------------------------- SELECT whose options can't express the answer
def test_legal_select_with_unmappable_options_is_human_required():
    r = resolve_form_field(
        _f("Will you now or in the future require sponsorship?", kind=InputKind.SELECT,
           options=["I am a U.S. citizen", "I have permanent work authorization"]),
        _profile(), "/tmp/r.pdf",
    )
    assert r.status.value in {"HUMAN_REQUIRED", "BLOCKED"}
