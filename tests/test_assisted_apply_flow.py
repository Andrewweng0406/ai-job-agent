"""Human-in-the-loop assisted apply: review packet + answer validation + no-submit guard."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.applications.assisted_answers import AnswersError, load_answers
from app.applications.form_engine import FormFieldResolution, FormFieldStatus, InputKind, RawFormField
from app.applications.form_fields import FieldPolicy
from app.applications.review_packet import build_review_packet


def _raw(label, selector, required=True, options=None, kind=InputKind.TEXT):
    return RawFormField(label=label, kind=kind, selector=selector, required=required, options=options or [])


def _res(label, selector, status, *, kind=InputKind.TEXT, value=None, canonical_key=None,
         policy=None, reason=None, legal_sensitive=False, required=True):
    return FormFieldResolution(label=label, selector=selector, kind=kind, required=required,
                               status=status, canonical_key=canonical_key, value=value,
                               policy=policy, reason=reason, legal_sensitive=legal_sensitive,
                               source={"fact_id": "name.full"} if value else {})


def _packet():
    raw = [
        _raw("First Name *", "id=first_name"),
        _raw("Email *", "id=email"),
        _raw("Country *", "id=country", options=["United States", "Canada"]),
        _raw("Why do you want to work here? *", "id=why", kind=InputKind.LONG_TEXT),
        _raw("LinkedIn", "id=linkedin", required=False),
    ]
    res = [
        _res("First Name *", "id=first_name", FormFieldStatus.FILLED, value="Test", canonical_key="personal.first_name"),
        _res("Email *", "id=email", FormFieldStatus.FILLED, value="a@b.test", canonical_key="email"),
        _res("Country *", "id=country", FormFieldStatus.HUMAN_REQUIRED, reason="FORM_MAPPING"),
        _res("Why do you want to work here? *", "id=why", FormFieldStatus.HUMAN_REQUIRED, reason="HUMAN_REQUIRED"),
        _res("LinkedIn", "id=linkedin", FormFieldStatus.SKIPPED, required=False, reason="OPTIONAL_SKIP"),
    ]
    return build_review_packet(company="Acme", role="Analyst", apply_url="https://x.test/a",
                               ats="greenhouse", raw_fields=raw, resolutions=res)


def test_packet_splits_safe_from_human_and_never_exposes_raw_values():
    p = _packet()
    assert [s.label for s in p.safe_prefill] == ["First Name *", "Email *"]
    assert p.optional_skipped == 1
    assert {q.label for q in p.needs_your_answer} == {"Country *", "Why do you want to work here? *"}
    # email hint is masked, not the raw address
    email_hint = next(s.value_hint for s in p.safe_prefill if s.canonical_key == "email")
    assert "@b.test" in email_hint and "a@b.test" != email_hint
    assert p.ready_for_assisted_fill is True


def test_legal_sensitive_filled_value_is_hidden_in_the_hint():
    raw = [_raw("Work authorization *", "id=wa")]
    res = [_res("Work authorization *", "id=wa", FormFieldStatus.FILLED, value="citizen",
               policy=FieldPolicy.NEVER_GUESS, legal_sensitive=True)]
    p = build_review_packet(company="A", role="R", apply_url="u", ats="greenhouse",
                            raw_fields=raw, resolutions=res)
    assert p.safe_prefill[0].value_hint == "[hidden]"


def test_blocked_field_makes_packet_not_ready():
    raw = [_raw("Resume *", "id=resume", kind=InputKind.FILE)]
    res = [_res("Resume *", "id=resume", FormFieldStatus.BLOCKED, kind=InputKind.FILE,
               reason="TRUTH_VALIDATION_FAILED")]
    p = build_review_packet(company="A", role="R", apply_url="u", ats="greenhouse",
                            raw_fields=raw, resolutions=res)
    assert p.ready_for_assisted_fill is False
    assert p.blocked[0].label == "Resume *"


def _write(tmp_path, body: str) -> Path:
    f = tmp_path / "answers.yaml"
    f.write_text(body)
    return f


def test_answers_require_every_required_open_question(tmp_path):
    f = _write(tmp_path, "approved_by: andrew\napproved_at: 2026-09-08T10:00:00-07:00\nanswers:\n  q2: United States\n")
    with pytest.raises(AnswersError, match="missing required answers"):
        load_answers(f, _packet())


def test_answers_reject_missing_approval(tmp_path):
    f = _write(tmp_path, "answers:\n  q2: United States\n  q3: Because reasons\n")
    with pytest.raises(AnswersError, match="approved_by"):
        load_answers(f, _packet())


def test_answers_reject_option_not_in_allowed_set(tmp_path):
    f = _write(tmp_path, "approved_by: a\napproved_at: 2026-09-08T10:00:00-07:00\n"
                         "answers:\n  q2: Mexico\n  q3: Because reasons\n")
    with pytest.raises(AnswersError, match="not one of the allowed options"):
        load_answers(f, _packet())


def test_answers_accept_a_complete_approved_set(tmp_path):
    f = _write(tmp_path, "approved_by: andrew\napproved_at: 2026-09-08T10:00:00-07:00\n"
                         "answers:\n  q2: United States\n  q3: I admire the mission.\n")
    approved = load_answers(f, _packet())
    assert approved.approved_by == "andrew"
    assert approved.answers["q2"] == "United States"


def test_assisted_apply_script_has_no_submit_primitive():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "assisted_apply.py").read_text()
    for banned in (".requestSubmit(", ".submit()", '.press("Enter")', ".press('Enter')",
                   '.press("Return")', 'click("[type=submit', 'click("button[type=submit',
                   "get_by_role(\"button\", name=\"Submit"):
        assert banned not in src, f"assisted_apply.py contains a submit primitive: {banned}"
    # keyboard.press is allowed only for non-activating keys
    import re as _re
    for m in _re.findall(r'keyboard\.press\(["\']([^"\']+)["\']\)', src):
        assert m in {"Escape", "Tab"}, f"assisted_apply.py presses an activating key: {m}"
    assert "real_submission_enabled=True" not in src
    assert "real_submission_enabled =" not in src
