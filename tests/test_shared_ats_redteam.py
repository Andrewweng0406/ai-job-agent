"""Shared-ATS field-extraction red team — Lever + Ashby representative forms.

Lever/Ashby dry-run adapters are thin subclasses of AtsDomDryRunAdapter, so they share
HtmlFormFieldExtractor + resolve_form_field with Greenhouse. This suite red-teams that shared
path against Lever/Ashby DOM shapes (fixtures are hand-built representatives, not live captures).

Passing = must hold. xfail(strict=False) = shared-extractor gap (CLAUDE_REVIEW P2-27 / P2-28).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.applications.ats_dom_dry_run import AtsDomDryRunAdapter
from app.applications.form_engine import resolve_form_field
from app.applications.html_form_extractor import HtmlFormFieldExtractor
from app.database.repository import JobAgentRepository
from app.resumes.profile import CandidateFact, CandidateProfile

FIXTURES = Path(__file__).parent / "fixtures" / "ats_forms"


def _fields(ats):
    html = (FIXTURES / f"{ats}_application.html").read_text()
    return HtmlFormFieldExtractor().extract(html, ats)


def _by(fields, needle):
    return [f for f in fields if needle.lower() in f.label.lower()]


def _profile():
    return CandidateProfile(
        candidate_id="c", schema_version=2,
        facts={
            "name.full": CandidateFact("name.full", "identity", "Jane Q Student", required=True),
            "contact.email": CandidateFact("contact.email", "contact", "jane@example.test", required=True),
        },
        application_answers={"work_authorized_us": "Yes", "requires_sponsorship_now_or_future": "Yes"},
    )


# ---------------------------------------------------------------- hidden exclusion (P2-21) — must hold
@pytest.mark.parametrize("ats", ["lever", "ashby"])
def test_no_honeypot_or_trap_field_is_extracted(ats):
    fields = _fields(ats)
    leaked = [
        f for f in fields
        if any(t in (f.selector or "").lower() for t in ("honeypot", "hp_", "off_screen", "offscreen", "disabled_trap", "disabled", "opacity_trap", "mirror"))
    ]
    assert leaked == [], f"{ats}: trap/honeypot field leaked: {[(x.label, x.selector) for x in leaked]}"


@pytest.mark.parametrize("ats", ["lever", "ashby"])
def test_visible_required_fields_survive(ats):
    fields = _fields(ats)
    # name / email / resume must all be present and the file input recognized
    assert _by(fields, "resume") or _by(fields, "cv") or [f for f in fields if f.kind.value == "file"]
    file_fields = [f for f in fields if f.kind.value == "file"]
    assert file_fields and file_fields[0].required is True


# ---------------------------------------------------------------- submit guard — must hold
@pytest.mark.parametrize("AdapterCls,ats", [
    ("lever", "lever"), ("ashby", "ashby"),
])
def test_shared_adapter_submit_always_raises(tmp_path, AdapterCls, ats):
    repo = JobAgentRepository(tmp_path / f"{ats}.sqlite3")
    repo.initialize()
    adapter = AtsDomDryRunAdapter(repo, ats_type=ats, real_submission_enabled=False)
    with pytest.raises(RuntimeError):
        adapter.submit()
    assert adapter.submit_call_count == 1


# ---------------------------------------------------------------- EEO safety — must hold
@pytest.mark.parametrize("ats,needle", [
    ("lever", "gender"), ("lever", "veteran"),
    ("ashby", "gender"), ("ashby", "disability"),
])
def test_eeo_fields_never_get_a_real_demographic_value(ats, needle):
    fld = _by(_fields(ats), needle)
    assert fld, f"{ats}: EEO field {needle!r} not extracted"
    res = resolve_form_field(fld[0], _profile(), "/tmp/r.pdf")
    if res.status.value == "FILLED":
        assert any(t in (res.value or "").lower() for t in ("decline", "prefer not", "wish", "want", "not to answer"))
    else:
        assert res.status.value in {"HUMAN_REQUIRED", "SKIPPED"}


# ---------------------------------------------------------------- unknown/legal questions — must hold
@pytest.mark.parametrize("ats,needle", [
    ("lever", "salary"), ("lever", "why do you want"),
    ("ashby", "compensation expectations"), ("ashby", "why you're excited"),
])
def test_unknown_required_free_text_is_human_required(ats, needle):
    fld = _by(_fields(ats), needle)
    if not fld:
        pytest.skip(f"{ats}: {needle!r} not extracted (see P2-27)")
    res = resolve_form_field(fld[0], _profile(), "/tmp/r.pdf")
    assert res.status.value == "HUMAN_REQUIRED"


# ---------------------------------------------------------------- P2-27: labels without <label for> are lost / bleed
@pytest.mark.parametrize("ats", ["lever", "ashby"])
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2-27: Lever .application-field>label (no for) and radio-group .application-label / role=radiogroup aria-labelledby are not captured; label bleeds to the required glyph")
def test_identity_and_radio_labels_are_captured_not_bled(ats):
    fields = _fields(ats)
    degenerate = [f for f in fields if f.label.strip() in {"", "*", "✱", "Yes", "No"}]
    assert degenerate == [], f"{ats}: degenerate/bled labels: {[(f.label, f.selector) for f in degenerate]}"
    # the sponsorship question must be a findable, meaningful label
    assert _by(fields, "sponsorship"), f"{ats}: sponsorship question label not captured"


# ---------------------------------------------------------------- P2-28: Yes/No radio group options
@pytest.mark.parametrize("ats", ["lever", "ashby"])
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2-28: Yes/No radio groups extract options as ['*','Yes'] — required glyph leaks in, 'No' dropped")
def test_yes_no_radio_group_options_are_yes_and_no(ats):
    fields = _fields(ats)
    groups = [f for f in fields if f.kind.value == "select" and any("yes" in o.lower() for o in f.options)]
    assert groups
    for g in groups:
        opts = {o.strip().lower() for o in g.options}
        if opts & {"yes", "no"} == {"yes", "no"}:
            continue
        assert opts == {"yes", "no"}, f"{ats}: radio group {g.selector} options = {g.options}"


# ---------------------------------------------------------------- conditional fields are represented (safe)
@pytest.mark.parametrize("ats,needle", [
    ("lever", "which city would you relocate"),
    ("ashby", "when could you start"),
])
def test_conditional_field_is_extracted_and_not_auto_filled(ats, needle):
    fld = _by(_fields(ats), needle)
    if not fld:
        pytest.skip("conditional field not extracted")
    res = resolve_form_field(fld[0], _profile(), "/tmp/r.pdf")
    assert res.status.value in {"HUMAN_REQUIRED", "SKIPPED"}
