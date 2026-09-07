from app.applications.form_engine import FormDryRunEngine, FormFieldStatus, InputKind, RawFormField, resolve_form_field
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateFact, CandidateProfile


def test_resolves_known_fields_and_builds_submit_ready_transcript(tmp_path):
    repo, job, app_id = _repo_job_app(tmp_path)
    profile = _profile(
        facts={
            "name.full": "Andrew Weng",
            "contact.email": "andrew@example.test",
            "contact.phone": "+1 555 010 2222",
        },
        answers={"work_authorized_us": "Yes", "requires_sponsorship_now_or_future": "Yes"},
    )
    fields = [
        RawFormField("First Name", InputKind.TEXT, "#first", required=True),
        RawFormField("Last Name", InputKind.TEXT, "#last", required=True),
        RawFormField("Email", InputKind.TEXT, "#email", required=True),
        RawFormField("Phone", InputKind.TEXT, "#phone", required=True),
        RawFormField("Resume", InputKind.FILE, "#resume", required=True),
        RawFormField("Are you authorized to work in the United States?", InputKind.SELECT, "#auth", required=True),
        RawFormField("Will you now or in the future require sponsorship?", InputKind.SELECT, "#sponsor", required=True),
        RawFormField("GitHub URL", InputKind.TEXT, "#github", required=False),
    ]

    result = FormDryRunEngine(repo, real_submission_enabled=False).build_transcript(
        application_id=app_id,
        job=job,
        profile=profile,
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="abc123",
        fields=fields,
    )

    assert result.status == ApplicationStatus.READY
    assert result.transcript.would_submit
    assert repo.get_application_status(app_id) == ApplicationStatus.READY
    assert {r.status for r in result.resolutions} == {FormFieldStatus.FILLED, FormFieldStatus.SKIPPED}
    payload = result.transcript.payload
    assert payload["real_submission_enabled"] is False
    assert payload["would_submit"] is True
    assert payload["unresolved"] == []

    with repo.connect() as conn:
        row = conn.execute("SELECT would_submit, payload_hash FROM dry_run_transcripts WHERE transcript_id = ?", (result.transcript.transcript_id,)).fetchone()
    assert row["would_submit"] == 1
    assert row["payload_hash"] == result.transcript.payload_hash()


def test_missing_required_profile_fact_opens_human_task(tmp_path):
    repo, job, app_id = _repo_job_app(tmp_path)
    profile = _profile(facts={"name.full": "Andrew Weng"}, answers={})
    fields = [RawFormField("Email", InputKind.TEXT, "#email", required=True)]

    result = FormDryRunEngine(repo).build_transcript(
        application_id=app_id,
        job=job,
        profile=profile,
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="abc123",
        fields=fields,
    )

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.transcript.would_submit is False
    assert repo.get_application_status(app_id) == ApplicationStatus.HUMAN_REQUIRED
    assert result.resolutions[0].status == FormFieldStatus.BLOCKED
    assert result.resolutions[0].reason == "PROFILE_INCOMPLETE:contact.email"
    with repo.connect() as conn:
        task = conn.execute("SELECT category, context_json FROM human_tasks WHERE application_id = ?", (app_id,)).fetchone()
    assert task["category"] == "PROFILE_INCOMPLETE"
    assert result.transcript.transcript_id in task["context_json"]


def test_legal_unknown_and_required_custom_fields_are_human_required():
    profile = _profile(facts={"name.full": "Andrew Weng"}, answers={})
    legal = resolve_form_field(
        RawFormField("Describe your immigration status", InputKind.LONG_TEXT, "#legal", required=True),
        profile,
        "resume.pdf",
    )
    essay = resolve_form_field(
        RawFormField("Why do you want to work here?", InputKind.LONG_TEXT, "#essay", required=True),
        profile,
        "resume.pdf",
    )

    assert legal.status == FormFieldStatus.HUMAN_REQUIRED
    assert legal.reason == "FIELD_REQUIRES_HUMAN"
    assert essay.status == FormFieldStatus.HUMAN_REQUIRED
    assert essay.reason == "FORM_MAPPING"


def test_required_optional_field_without_value_blocks_instead_of_guessing():
    profile = _profile(facts={}, answers={})
    result = resolve_form_field(
        RawFormField("GitHub URL", InputKind.TEXT, "#github", required=True),
        profile,
        "resume.pdf",
    )

    assert result.status == FormFieldStatus.HUMAN_REQUIRED
    assert result.reason == "OPTIONAL_SKIP"


def test_single_token_name_blocks_required_last_name():
    profile = _profile(facts={"name.full": "Prince"}, answers={})
    result = resolve_form_field(
        RawFormField("Last Name", InputKind.TEXT, "#last", required=True),
        profile,
        "resume.pdf",
    )

    assert result.status == FormFieldStatus.BLOCKED
    assert result.reason == "PROFILE_INCOMPLETE:name.full"


def _repo_job_app(tmp_path):
    repo = JobAgentRepository(tmp_path / "form.sqlite3")
    repo.initialize()
    job = Job(
        external_job_id="job-1",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="Entry-level analytics.",
        source="fixture",
        source_url="https://example.test/job",
        apply_url="https://example.test/apply",
        ats_type="fixture",
        job_family=JobFamily.DATA_ANALYTICS,
    )
    job_id = repo.upsert_job(job)
    job.id = job_id
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="fixture",
        ats_type="fixture",
        status=ApplicationStatus.READY,
    )
    app_id = repo.insert_application(app)
    return repo, job, app_id


def _profile(facts, answers):
    return CandidateProfile(
        candidate_id="cand",
        schema_version=2,
        facts={
            fact_id: CandidateFact(fact_id=fact_id, type="profile", value=value)
            for fact_id, value in facts.items()
        },
        application_answers=answers,
    )
