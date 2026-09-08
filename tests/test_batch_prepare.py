"""batch_prepare.build_batch_record: profile -> standard answer -> essay -> blocker."""
from __future__ import annotations

import json

import pytest

from app.applications.batch_prepare import BatchRecord, build_batch_record
from app.applications.form_engine import FormFieldResolution, FormFieldStatus, InputKind, RawFormField
from app.applications.form_fields import FieldPolicy
from app.applications.standard_answers import StandardAnswers

STD = StandardAnswers.from_yaml("config/standard_answers.local.yaml") if __import__("pathlib").Path(
    "config/standard_answers.local.yaml").exists() else None

_RULES = json.dumps({
    "answers": {"work_authorized_us": "Yes", "salary_expectation": "Open / negotiable",
                "gender": "Decline to self-identify"},
    "match": [
        {"key": "work_authorized_us", "phrases": ["authorized to work"]},
        {"key": "salary_expectation", "phrases": ["salary expectation"]},
        {"key": "gender", "phrases": ["gender identity"]},
    ],
})


@pytest.fixture
def std(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_RULES)
    return StandardAnswers.from_yaml(p)


class _EssayOK:
    def write(self, **_):
        from app.llm.essay import EssayResult
        return EssayResult(True, text="I admire Acme's data platform and my SQL projects fit the role.")


class _EssayRejected:
    def write(self, **_):
        from app.llm.essay import EssayResult
        return EssayResult(False, reason="ESSAY_OVERREACH:senior engineer")


class _ExperienceOK:
    def answer_experience(self, **_):
        from app.llm.essay import EssayResult
        return EssayResult(True, text="On my Earnings Radar project I built an NLP pipeline in Python "
                                      "that parsed transcripts and surfaced the metrics that drove our picks.")


def _raw(label, sel, required=True, options=None, kind=InputKind.TEXT):
    return RawFormField(label=label, kind=kind, selector=sel, required=required, options=options or [])


def _res(label, sel, status, *, kind=InputKind.TEXT, value=None, required=True, policy=None, legal=False):
    return FormFieldResolution(label=label, selector=sel, kind=kind, required=required, status=status,
                              value=value, policy=policy, legal_sensitive=legal,
                              source={"fact_id": "x"} if value else {})


def _build(std, raw, res, **kw):
    return build_batch_record(company="Acme", role="Analyst", apply_url="https://x.test/a",
                              ats="greenhouse", resume_pdf="r.pdf", raw_fields=raw, resolutions=res,
                              standard_answers=std, jd_excerpt="Use SQL.", **kw)


def test_profile_and_standard_answers_make_a_ready_record(std):
    raw = [_raw("First name", "id=fn"), _raw("Authorized to work in the US?", "id=wa", options=["Yes", "No"]),
           _raw("Salary expectation", "id=sal", required=False)]
    res = [_res("First name", "id=fn", FormFieldStatus.FILLED, value="Andrew"),
           _res("Authorized to work in the US?", "id=wa", FormFieldStatus.HUMAN_REQUIRED),
           _res("Salary expectation", "id=sal", FormFieldStatus.HUMAN_REQUIRED, required=False)]
    rec = _build(std, raw, res)
    assert rec.ready
    src = {f.field_id: f.source for f in rec.fields}
    assert src == {"q0": "profile", "q1": "standard_answer", "q2": "standard_answer"}
    assert rec.fill_map() == {"id=fn": "Andrew", "id=wa": "Yes", "id=sal": "Open / negotiable"}


def test_unmapped_required_field_blocks(std):
    raw = [_raw("What is your favourite database?", "id=db")]
    res = [_res("What is your favourite database?", "id=db", FormFieldStatus.HUMAN_REQUIRED)]
    rec = _build(std, raw, res)
    assert not rec.ready
    assert rec.fields[0].source == "unresolved"
    assert any("unmapped" in b for b in rec.blockers)


def test_essay_question_uses_the_writer_when_it_succeeds(std):
    raw = [_raw("Why do you want to work at Acme?", "id=why", kind=InputKind.LONG_TEXT)]
    res = [_res("Why do you want to work at Acme?", "id=why", FormFieldStatus.HUMAN_REQUIRED, kind=InputKind.LONG_TEXT)]
    rec = _build(std, raw, res, essay_writer=_EssayOK())
    assert rec.ready
    assert rec.fields[0].source == "essay"
    assert rec.essay_text and "Acme" in rec.essay_text
    assert rec.fill_map()["id=why"] == rec.essay_text


def test_rejected_essay_blocks_and_is_not_filled(std):
    raw = [_raw("Why Acme?", "id=why", kind=InputKind.LONG_TEXT)]
    res = [_res("Why Acme?", "id=why", FormFieldStatus.HUMAN_REQUIRED, kind=InputKind.LONG_TEXT)]
    rec = _build(std, raw, res, essay_writer=_EssayRejected())
    assert not rec.ready
    assert rec.fields[0].source == "unresolved"
    assert "id=why" not in rec.fill_map()
    assert rec.essay_reason == "ESSAY_OVERREACH:senior engineer"


def test_experience_question_is_drafted_when_a_writer_is_available(std):
    raw = [_raw("Describe a time you used data to improve a decision.", "id=story", kind=InputKind.LONG_TEXT)]
    res = [_res("Describe a time you used data to improve a decision.", "id=story",
               FormFieldStatus.HUMAN_REQUIRED, kind=InputKind.LONG_TEXT)]
    rec = _build(std, raw, res, essay_writer=_ExperienceOK())
    assert rec.ready
    assert rec.fields[0].source == "essay"
    assert "id=story" in rec.fill_map()


def test_experience_question_blocks_without_a_writer(std):
    raw = [_raw("Describe a time you used data to improve a decision.", "id=story", kind=InputKind.LONG_TEXT)]
    res = [_res("Describe a time you used data to improve a decision.", "id=story",
               FormFieldStatus.HUMAN_REQUIRED, kind=InputKind.LONG_TEXT)]
    rec = _build(std, raw, res, essay_writer=None)
    assert not rec.ready
    assert rec.fields[0].source == "must_queue"


def test_reference_request_always_blocks(std):
    raw = [_raw("Please provide two professional references.", "id=refs", kind=InputKind.LONG_TEXT)]
    res = [_res("Please provide two professional references.", "id=refs", FormFieldStatus.HUMAN_REQUIRED,
               kind=InputKind.LONG_TEXT)]
    rec = _build(std, raw, res, essay_writer=_ExperienceOK())
    assert not rec.ready
    assert rec.fields[0].source == "must_queue"


def test_legal_sensitive_value_is_masked_in_display(std):
    raw = [_raw("Work authorization detail", "id=wad")]
    res = [_res("Work authorization detail", "id=wad", FormFieldStatus.FILLED, value="citizen",
               policy=FieldPolicy.NEVER_GUESS, legal=True)]
    rec = _build(std, raw, res)
    assert rec.fields[0].display == "[hidden]"
    assert rec.fields[0].value == "citizen"  # still filled, just not shown on the card


def test_record_round_trips_through_dict(std):
    raw = [_raw("First name", "id=fn")]
    res = [_res("First name", "id=fn", FormFieldStatus.FILLED, value="Andrew")]
    rec = _build(std, raw, res)
    again = BatchRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert again.fill_map() == rec.fill_map()
    assert again.ready == rec.ready
