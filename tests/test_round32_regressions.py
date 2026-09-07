"""Round 3.2 independent re-verification of Codex's claimed fixes.

P1-25  submit_attempted_at reclaim guard
P1-26  hidden/honeypot field exclusion (+ what is still missed)
P1-27  no submitting keypress anywhere in the browser/autofill path
P2-18  EEO decline maps to real ATS option wording
P2-20  HTTP client does not retry arbitrary 4xx
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.applications import browser_autofill, greenhouse_live
from app.applications.ats_dom_dry_run import AtsDomDryRunAdapter
from app.applications.form_engine import InputKind, RawFormField, resolve_form_field
from app.applications.html_form_extractor import HtmlFormFieldExtractor
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateFact, CandidateProfile


# ---------------------------------------------------------------- P1-25
def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "r.sqlite3")
    r.initialize()
    return r


def _ready(repo, ext="j1"):
    job = Job(external_job_id=ext, company_id="acme", company_name="Acme", title="Data Analyst",
              location="Remote", description="x", source="fixture", source_url=f"https://e/{ext}",
              apply_url=f"https://e/apply/{ext}", ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS)
    job.id = repo.upsert_job(job)
    app = Application(job_id=job.id, company="Acme", position="Data Analyst", location="Remote",
                     job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    app_id = repo.insert_application(app)
    for s in [ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED, ApplicationStatus.TAILORING, ApplicationStatus.READY]:
        repo.transition_application(app_id, s, "seed")
    return app_id


def _future(minutes):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def test_row_with_submit_marker_cannot_be_claimed_from_ready(tmp_path):
    repo = _repo(tmp_path)
    app_id = _ready(repo)
    repo.mark_submit_attempted(app_id)
    # even though the row is READY, the submit marker must block a fresh claim
    assert repo.claim_next_application(ApplicationStatus.READY, "w1", _future(10)) is None


def test_row_with_submit_marker_cannot_be_claimed_from_retry_pending(tmp_path):
    repo = _repo(tmp_path)
    app_id = _ready(repo)
    repo.claim_next_application(ApplicationStatus.READY, "w1", _future(-1))  # -> APPLYING, lease expired
    repo.mark_submit_attempted(app_id)
    repo.reap_expired_leases()  # -> SUBMISSION_UNKNOWN (marker set)
    assert repo.get_application_status(app_id) == ApplicationStatus.SUBMISSION_UNKNOWN
    # cannot be resurrected into a claimable state that still carries the marker
    assert repo.claim_next_application(ApplicationStatus.RETRY_PENDING, "w2", _future(10)) is None


def test_human_skip_is_the_only_thing_that_clears_the_marker(tmp_path):
    repo = _repo(tmp_path)
    app_id = _ready(repo)
    repo.claim_next_application(ApplicationStatus.READY, "w1", _future(-1))
    repo.mark_submit_attempted(app_id)
    repo.reap_expired_leases()
    repo.transition_application(app_id, ApplicationStatus.SKIPPED, "human: never actually submitted")
    with repo.connect() as conn:
        val = conn.execute("SELECT submit_attempted_at FROM applications WHERE application_id=?", (app_id,)).fetchone()[0]
    assert val is None


# ---------------------------------------------------------------- P1-26
def test_honeypot_display_none_aria_hidden_is_excluded():
    html = (
        "<form><label for=e>Email</label><input id=e name=email required>"
        "<input type=text name='job_application[hp_email]' style='display:none' aria-hidden='true' tabindex='-1'>"
        "</form>"
    )
    fields = HtmlFormFieldExtractor().extract(html, "greenhouse")
    assert all("hp_email" not in f.selector for f in fields)
    assert [f.label for f in fields] == ["Email"]


@pytest.mark.parametrize(
    "hidden_attr",
    [
        "hidden",                                   # bare HTML hidden attribute
        "disabled",                                 # disabled trap
        "style='position:absolute;left:-9999px'",   # offscreen decoy
        "style='opacity:0'",
    ],
)
def test_other_hidden_field_techniques_are_also_excluded(hidden_attr):
    html = f"<form><label for=e>Email</label><input id=e name=email required><input type=text name=trap {hidden_attr}></form>"
    fields = HtmlFormFieldExtractor().extract(html, "greenhouse")
    assert all("trap" not in f.selector for f in fields), f"trap field via {hidden_attr!r} leaked"


def test_legitimate_controls_are_not_dropped_as_hidden():
    html = "<form><label for=a>First</label><input id=a name=first required><label for=b>Last</label><input id=b name=last required></form>"
    fields = HtmlFormFieldExtractor().extract(html, "greenhouse")
    assert {f.label for f in fields} == {"First", "Last"}


# ---------------------------------------------------------------- P1-27
def test_no_submitting_keypress_in_browser_or_autofill_path():
    for mod in (browser_autofill, greenhouse_live):
        src = inspect.getsource(mod)
        for banned in ('press("Enter")', "press('Enter')", '"Return"', "'Return'",
                       "requestSubmit", "form.submit(", ".submit()", "dispatch_event(\"submit\"", "keyboard.press"):
            assert banned not in src, f"{mod.__name__} contains a submitting primitive: {banned}"


def test_dry_run_adapter_has_no_callable_submit_that_succeeds(tmp_path):
    repo = _repo(tmp_path)
    adapter = AtsDomDryRunAdapter(repo, ats_type="greenhouse", real_submission_enabled=False)
    with pytest.raises(RuntimeError):
        adapter.submit()


# ---------------------------------------------------------------- P2-18
def _profile():
    return CandidateProfile("c", 2, {}, {"work_authorized_us": "Yes"})


@pytest.mark.parametrize(
    "options",
    [
        ["Decline To Self Identify", "Male", "Female"],
        ["Prefer not to answer", "Asian", "White"],
        ["I do not wish to disclose", "Yes", "No"],
        ["Choose not to answer", "Veteran", "Not a veteran"],
        ["I don't wish to self-identify", "Yes", "No"],
    ],
)
def test_eeo_decline_maps_to_a_safe_option(options):
    field = RawFormField(label="Gender", kind=InputKind.SELECT, selector="s", required=False, options=options)
    res = resolve_form_field(field, _profile(), "/tmp/r.pdf")
    if res.status.value == "FILLED":
        assert res.value in options
        assert any(t in res.value.lower() for t in ("decline", "prefer not", "wish", "choose not", "not to answer"))
    else:
        assert res.status.value in {"HUMAN_REQUIRED", "SKIPPED"}


def test_eeo_never_selects_a_real_demographic_value():
    field = RawFormField(label="Race / Ethnicity", kind=InputKind.SELECT, selector="s", required=False,
                         options=["Asian", "White", "Black or African American"])  # NO decline option
    res = resolve_form_field(field, _profile(), "/tmp/r.pdf")
    assert res.status.value != "FILLED" or res.value not in ("Asian", "White", "Black or African American")


# ---------------------------------------------------------------- P2-20
@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_http_client_does_not_retry_4xx(code, monkeypatch):
    from email.message import Message
    from urllib.error import HTTPError

    from app.utils import http
    from app.utils.http import HttpClientConfig, HttpClientError, JsonHttpClient

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, code, "err", Message(), None)

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    client = JsonHttpClient(HttpClientConfig(retries=5, per_host_requests_per_second=0, jitter_seconds=0))
    with pytest.raises(HttpClientError):
        client.get_json("https://api.example.test/x")
    assert len(calls) == 1, f"{code} was retried {len(calls)} times"
