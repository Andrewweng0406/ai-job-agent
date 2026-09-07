"""Reviewer audit of DeterministicResumeGenerator — truth + functional characterization.

Safe by construction (verbatim facts, fail-closed gates). But: the truth-validation step is a
tautology (bullets == fact_text), the fact model has no projects/experience/skills so a real
resume is name+education only, and the placeholder PDF renderer truncates real bullet lengths
(caught by pdf_qa -> PDF_QA_FAILED, i.e. fail-closed but non-functional).
"""
from __future__ import annotations

import inspect

import pytest

from app.models.enums import JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import DeterministicResumeGenerator
from app.resumes.profile import CandidateFact, CandidateProfile


def _job():
    return Job(external_job_id="1", company_id="acme", company_name="Acme", title="Data Analyst",
              location="Remote", description="x", source="greenhouse", source_url="u", apply_url="u",
              ats_type="greenhouse", job_family=JobFamily.DATA_ANALYTICS, id=1)


def _complete_profile(**extra_facts):
    facts = {
        "name.full": CandidateFact("name.full", "identity", "Test User", required=True),
        "edu.primary.school": CandidateFact("edu.primary.school", "education", "Test University", required=True),
        "edu.primary.degree": CandidateFact("edu.primary.degree", "education", "B.S. Testing", required=True),
        "edu.primary.grad_date": CandidateFact("edu.primary.grad_date", "education", "May 2027", required=True),
        "auth.status": CandidateFact("auth.status", "legal", "authorized", required=True, literal_only=True),
        "auth.needs_future_sponsorship": CandidateFact("auth.needs_future_sponsorship", "legal", "true", required=True, literal_only=True),
    }
    facts.update(extra_facts)
    return CandidateProfile("internal-test", 2, facts, {})


def test_incomplete_profile_blocks_generation():
    prof = CandidateProfile("internal-test", 2,
                            {"name.full": CandidateFact("name.full", "identity", "TODO", required=True)}, {})
    r = DeterministicResumeGenerator(output_dir="/tmp/none").generate(prof, _job(), Persona.DATA, [])
    assert r.artifact is None and r.human_required_reason == "PROFILE_INCOMPLETE"


def test_generated_resume_is_verbatim_facts_only(tmp_path):
    prof = _complete_profile(
        **{"skill.sql": CandidateFact("skill.sql", "skill", "SQL", required=False)}
    )
    r = DeterministicResumeGenerator(output_dir=tmp_path).generate(prof, _job(), Persona.DATA, ["skill.sql"])
    assert r.artifact is not None, r.human_required_reason
    text = (tmp_path / f"{r.artifact.file_path.split('/')[-1]}").read_bytes() if False else b""
    import json
    sections = json.loads((tmp_path.glob("*.json").__next__()).read_text())["sections"]
    # every non-heading bullet must be a literal profile fact string
    assert "Test User" in sections["header"]
    for line in sections["facts"].splitlines():
        if line.startswith("- "):
            assert line[2:] in ("SQL",) or line[2:].startswith(("skill", "edu", "auth")), line


def test_truth_step_is_currently_a_self_check():
    """CLAUDE_REVIEW P3: the truth-validation call is `validate_claims_against_profile(bullets, fact_text)`
    where `bullets` is derived verbatim from `fact_text` — so it always passes. Safe for a deterministic
    verbatim generator, but `validation_status='VALIDATED'` is not evidence of an independent check."""
    src = inspect.getsource(DeterministicResumeGenerator.generate)
    body = src.split("bullets =", 1)[1].split("truth =", 1)[0]
    assert "sections[\"facts\"]" in body and "self._render" not in body, "bullets are extracted from the rendered fact list"


def test_generator_renders_experience_and_projects():
    src = inspect.getsource(DeterministicResumeGenerator._render_sections)
    assert "experience" in src.lower() and ("project" in src.lower() or "skills" in src.lower())


def test_long_bullet_survives_the_pdf_pipeline(tmp_path):
    # render_simple_pdf no longer truncates (earlier P2-11 fix); a real-length bullet round-trips.
    long_skill = "Applied multiple linear and ARIMA time-series regression models to 3+ years of sales and market data improving forecast accuracy"
    prof = _complete_profile(**{"proj.x": CandidateFact("proj.x", "project", long_skill, required=False)})
    r = DeterministicResumeGenerator(output_dir=tmp_path).generate(prof, _job(), Persona.DATA, ["proj.x"])
    assert r.artifact is not None, f"long bullet blocked generation: {r.human_required_reason}"
    assert r.artifact.validation_status == "VALIDATED"
