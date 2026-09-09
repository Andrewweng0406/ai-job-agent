from pathlib import Path

from app.applications.batch_prepare import resolve_scanned
from app.applications.live_field_scan import ScannedField
from app.applications.standard_answers import StandardAnswers
from app.resumes.profile import CandidateFact, CandidateProfile


def _answers(tmp_path: Path) -> StandardAnswers:
    config = tmp_path / "answers.yaml"
    config.write_text("""
answers: {}
approved_exact:
  - company: Acme
    label: I accept Acme's privacy policy.
    answer: I acknowledge
  - company: Acme
    label: Relocation destinations
    answer: New York, NY; San Francisco, CA
""")
    return StandardAnswers.from_yaml(config)


def test_exact_approval_requires_company_and_full_prompt_match(tmp_path):
    answers = _answers(tmp_path)

    assert answers.resolve_exact(
        "Acme", "I accept Acme's privacy policy.", ["I acknowledge"]
    ) == "I acknowledge"
    assert answers.resolve_exact(
        "Other", "I accept Acme's privacy policy.", ["I acknowledge"]
    ) is None
    assert answers.resolve_exact(
        "Acme", "I accept Acme's updated privacy policy.", ["I acknowledge"]
    ) is None


def test_exact_approval_maps_every_checkbox_option(tmp_path):
    answers = _answers(tmp_path)

    assert answers.resolve_exact(
        "Acme", "Relocation destinations", ["New York, NY", "San Francisco, CA"]
    ) == "New York, NY; San Francisco, CA"
    assert answers.resolve_exact(
        "Acme", "Relocation destinations", ["New York, NY"]
    ) is None


def test_education_start_controls_use_verified_profile_date(tmp_path):
    profile = CandidateProfile(
        "candidate", 2,
        {"edu.primary.start_date": CandidateFact(
            "edu.primary.start_date", "education", "August 2023"
        )}, {},
    )
    scanned = [
        ScannedField("Start date month*", "combobox", "id=start-month", True),
        ScannedField("Start date year*", "numeric", "id=start-year", True),
    ]

    record = resolve_scanned(
        company="Acme", role="Analyst", apply_url="https://example.test/job",
        ats="greenhouse", resume_pdf="resume.pdf", scanned=scanned, profile=profile,
        standard_answers=_answers(tmp_path),
    )

    assert record.fill_map() == {"id=start-month": "August", "id=start-year": "2023"}
