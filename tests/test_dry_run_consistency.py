"""Dry-run transcript consistency + no-submit guarantee (Round 3 WS4/WS6).

- FormDryRunEngine NEVER submits (returns READY / HUMAN_REQUIRED only).
- Unresolved required field -> HUMAN_REQUIRED + a human_task + would_submit == False.
- Transcript payload records resume id/hash + every field's value, status, and provenance source.
- Transcript payload is hash-stable for identical input (immutability precondition).
"""
from __future__ import annotations

from app.applications.form_engine import FormDryRunEngine, FormFieldStatus, InputKind, RawFormField
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import ResumeArtifact
from app.resumes.profile import CandidateProfile


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "dry.sqlite3")
    r.initialize()
    return r


def _job(repo) -> Job:
    job_id = repo.upsert_job(
        Job(external_job_id="j1", company_id="acme", company_name="Acme", title="Product Analyst",
            location="Remote", description="analytics", source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/1",
            apply_url="https://boards.greenhouse.io/acme/jobs/1", ats_type="greenhouse",
            job_family=JobFamily.PRODUCT_PM)
    )
    with repo.connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    j = Job(external_job_id=row["external_job_id"], company_id=row["company_id"], company_name=row["company_name"],
            title=row["title"], location=row["location"], description=row["description"], source=row["source"],
            source_url=row["source_url"], apply_url=row["apply_url"], ats_type=row["ats_type"],
            job_family=JobFamily(row["job_family"]))
    j.id = job_id
    return j


def _profile(**answers) -> CandidateProfile:
    from app.resumes.profile import CandidateFact
    facts = {
        "name.full": CandidateFact("name.full", "identity", "Jane Q Student", required=True),
        "contact.email": CandidateFact("contact.email", "contact", "jane@example.test", required=True),
        "contact.phone": CandidateFact("contact.phone", "contact", "555-0100", required=True),
        "edu.primary.school": CandidateFact("edu.primary.school", "education", "San Jose State University", required=True),
    }
    bank = {"work_authorized_us": "Yes", "requires_sponsorship_now_or_future": "Yes"}
    bank.update(answers)
    return CandidateProfile("cand", 2, facts, bank)


def _app(repo, job) -> str:
    a = Application(job_id=job.id, company="Acme", position="Product Analyst", location="Remote",
                    job_family=JobFamily.PRODUCT_PM, source="greenhouse", ats_type="greenhouse")
    repo.insert_application(a)
    for s in [ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED, ApplicationStatus.TAILORING, ApplicationStatus.READY]:
        repo.transition_application(a.application_id, s, "seed")
    return a.application_id


FULLY_RESOLVABLE = [
    RawFormField("First Name", InputKind.TEXT, "s1", required=True),
    RawFormField("Last Name", InputKind.TEXT, "s2", required=True),
    RawFormField("Email", InputKind.TEXT, "s3", required=True),
    RawFormField("Resume", InputKind.FILE, "s4", required=True),
    RawFormField("Will you now or in the future require sponsorship?", InputKind.SELECT, "s5", required=True),
]

WITH_UNRESOLVED = FULLY_RESOLVABLE + [
    RawFormField("Why do you want to work here?", InputKind.LONG_TEXT, "s6", required=True),
]


def _engine(repo):
    return FormDryRunEngine(repo, real_submission_enabled=False)


def test_dry_run_never_submits_and_returns_ready_when_resolved(tmp_path):
    repo = _repo(tmp_path); job = _job(repo); app_id = _app(repo, job)
    result = _engine(repo).build_transcript(
        application_id=app_id, job=job, profile=_profile(),
        resume_id="resume_1", resume_path="/artifacts/resume_1.pdf", resume_hash="sha256:abc",
        fields=FULLY_RESOLVABLE,
    )
    assert result.status == ApplicationStatus.READY
    assert result.transcript.would_submit is True
    # every filled field carries a provenance source
    for res in result.resolutions:
        if res.status == FormFieldStatus.FILLED:
            assert res.source, f"{res.label} FILLED with no source"
    # payload records resume id + hash
    assert result.transcript.payload["resume"]["resume_id"] == "resume_1"
    assert result.transcript.payload["resume"]["file_hash"] == "sha256:abc"


def test_dry_run_unresolved_field_blocks_and_opens_task(tmp_path):
    repo = _repo(tmp_path); job = _job(repo); app_id = _app(repo, job)
    result = _engine(repo).build_transcript(
        application_id=app_id, job=job, profile=_profile(),
        resume_id="resume_1", resume_path="/a/r.pdf", resume_hash="h",
        fields=WITH_UNRESOLVED,
    )
    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.transcript.would_submit is False
    assert repo.get_application_status(app_id) == ApplicationStatus.HUMAN_REQUIRED
    with repo.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM human_tasks WHERE application_id=? AND status IN ('OPEN','IN_PROGRESS')",
            (app_id,),
        ).fetchone()["c"]
    assert n >= 1


def test_transcript_payload_is_hash_stable(tmp_path):
    repo = _repo(tmp_path); job = _job(repo); app_id = _app(repo, job)
    eng = _engine(repo)
    kw = dict(application_id=app_id, job=job, profile=_profile(),
              resume_id="r", resume_path="/a/r.pdf", resume_hash="h", fields=FULLY_RESOLVABLE)
    t1 = eng.build_transcript(**kw).transcript
    t2 = eng.build_transcript(**kw).transcript
    assert t1.transcript_id != t2.transcript_id, "each build is a distinct row"
    assert t1.payload["fields"] == t2.payload["fields"], "identical inputs -> identical field payload"
    assert t1.payload["would_submit"] == t2.payload["would_submit"]


def test_dry_run_blocks_when_resume_not_validated(tmp_path):
    repo = _repo(tmp_path); job = _job(repo); app_id = _app(repo, job)
    repo.insert_resume_artifact(
        ResumeArtifact(
            resume_id="resume_bad",
            job_id=job.id,
            persona=Persona.PRODUCT_PM,
            base_version="test",
            generated_at="2026-09-07T00:00:00+00:00",
            changes={},
            validation_status="FAILED",
            file_path="/a/bad.pdf",
            file_hash="h",
        )
    )
    repo.attach_resume_to_application(app_id, "resume_bad")
    # resume artifact exists but its validation_status is not PASS -> resume field must NOT be FILLED
    result = _engine(repo).build_transcript(
        application_id=app_id, job=job, profile=_profile(),
        resume_id="resume_bad", resume_path="/a/bad.pdf", resume_hash="h",
        resume_validation_status="FAILED",
        fields=[RawFormField("Resume", InputKind.FILE, "s", required=True)],
    )
    resume_res = next(r for r in result.resolutions if r.canonical_key == "application.resume")
    assert resume_res.status != FormFieldStatus.FILLED


def test_multi_category_unresolved_opens_task_per_category(tmp_path):
    repo = _repo(tmp_path); job = _job(repo); app_id = _app(repo, job)
    result = _engine(repo).build_transcript(
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume_1",
        resume_path="/a/r.pdf",
        resume_hash="h",
        fields=[
            RawFormField("Desired annual compensation?", InputKind.TEXT, "salary", required=True),
            RawFormField("GitHub URL", InputKind.TEXT, "github", required=True),
        ],
    )

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    with repo.connect() as conn:
        categories = {
            row["category"]
            for row in conn.execute("SELECT category FROM human_tasks WHERE application_id = ?", (app_id,)).fetchall()
        }
    assert categories == {"FORM_MAPPING", "OPTIONAL_SKIP"}


def test_transcript_payload_has_persona_and_requisition_key_and_approval_hash(tmp_path):
    repo = _repo(tmp_path); job = _job(repo); app_id = _app(repo, job)
    transcript = _engine(repo).build_transcript(
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume_1",
        resume_path="/a/r.pdf",
        resume_hash="h",
        fields=FULLY_RESOLVABLE,
        persona="PRODUCT_PM",
    ).transcript

    assert transcript.payload["persona"] == "PRODUCT_PM"
    assert transcript.payload["job"]["requisition_key"]
    repo.approve_dry_run_transcript(transcript.transcript_id, "human@example.test")
    assert repo.dry_run_approval_is_valid(transcript.transcript_id, transcript.payload_hash())
    assert not repo.dry_run_approval_is_valid(transcript.transcript_id, "changed")
