from app.models.enums import JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import DeterministicResumeGenerator
from app.resumes.profile import CandidateProfile, profile_completeness_gate


def test_profile_completeness_gate_blocks_todo_required_fact(tmp_path):
    profile_file = tmp_path / "candidate.yaml"
    profile_file.write_text(
        """
meta:
  candidate_id: cand_test
  schema_version: 2
facts:
  - fact_id: name.full
    type: identity
    value: TODO
    required: true
application_answers: {}
""",
        encoding="utf-8",
    )
    profile = CandidateProfile.from_yaml(profile_file)
    result = profile_completeness_gate(profile)
    assert not result.complete
    assert result.missing_fact_ids == ["name.full"]


def test_deterministic_resume_generation_writes_validated_artifact(tmp_path):
    profile_file = tmp_path / "candidate.yaml"
    profile_file.write_text(
        """
meta:
  candidate_id: cand_test
  schema_version: 2
facts:
  - fact_id: name.full
    type: identity
    value: Jane Student
    required: true
  - fact_id: edu.bs.school
    type: education
    value: San Jose State University
    required: true
  - fact_id: edu.bs.degree
    type: education
    value: B.S. Business Analytics
    required: true
  - fact_id: edu.bs.grad_date
    type: education
    value: May 2026
    required: true
  - fact_id: skill.sql
    type: skill
    value: SQL
  - fact_id: project.retail
    type: project
    value: Built Tableau dashboards on retail data using SQL.
application_answers: {}
""",
        encoding="utf-8",
    )
    profile = CandidateProfile.from_yaml(profile_file)
    job = Job(
        external_job_id="1",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="SQL and dashboards.",
        source="fixture",
        source_url="https://example.test/job",
        apply_url="https://example.test/apply",
        ats_type="fixture",
        job_family=JobFamily.DATA_ANALYTICS,
        id=7,
    )

    result = DeterministicResumeGenerator(tmp_path / "resumes").generate(
        profile,
        job,
        Persona.DATA,
        selected_fact_ids=["skill.sql", "project.retail"],
    )

    assert result.artifact is not None
    assert result.artifact.validation_status == "VALIDATED"
    assert "Jane Student" in (tmp_path / "resumes" / f"{result.artifact.resume_id}.txt").read_text(encoding="utf-8")

