import sqlite3

from app.applications.browser_capture import BrowserFieldCapture
from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.models.enums import ApplicationStatus
from tests.test_greenhouse_dry_run import GREENHOUSE_FORM, _Page, _profile, _seed_ready_with_resume


def test_greenhouse_canary_records_expected_structure():
    capture = BrowserFieldCapture().capture(_Page(GREENHOUSE_FORM), ats_type="greenhouse")
    assert capture.form_detected
    assert capture.submit_control_detected
    assert capture.drift_reasons == []


def test_greenhouse_missing_submit_is_ats_changed(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    html = GREENHOUSE_FORM.replace('<button id="submit_app" type="submit">Submit Application</button>', "")

    result = GreenhouseDryRunAdapter(repo).dry_run(
        page=_Page(html), application_id=app_id, job=job, profile=_profile(),
        resume_id="resume-1", resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc", resume_validation_status="VALIDATED",
    )

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.reason == "ATS_CHANGED:MISSING_SUBMIT_CONTROL"


def test_greenhouse_closed_posting_closes_application(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    result = GreenhouseDryRunAdapter(repo).dry_run(
        page=_Page("<html><body><h1>This job is no longer available</h1></body></html>"),
        application_id=app_id, job=job, profile=_profile(), resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf", resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
    )
    assert result.status == ApplicationStatus.CLOSED
    assert repo.get_application_status(app_id) == ApplicationStatus.CLOSED


def test_dry_run_transcript_payload_is_database_immutable(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    result = GreenhouseDryRunAdapter(repo).dry_run(
        page=_Page(GREENHOUSE_FORM), application_id=app_id, job=job, profile=_profile(),
        resume_id="resume-1", resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc", resume_validation_status="VALIDATED",
    )
    with repo.connect() as conn:
        try:
            conn.execute(
                "UPDATE dry_run_transcripts SET payload_json = '{}' WHERE transcript_id = ?",
                (result.dry_run.transcript.transcript_id,),
            )
        except sqlite3.IntegrityError as exc:
            assert "immutable" in str(exc)
        else:
            raise AssertionError("transcript payload update should have been rejected")
