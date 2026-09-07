from app.filtering.hard_filters import apply_hard_filters
from app.models.enums import JobFamily
from app.models.job import Job


def make_job(title: str, description: str, family: JobFamily = JobFamily.DATA_ANALYTICS) -> Job:
    return Job(
        external_job_id="1",
        company_id="acme",
        company_name="Acme",
        title=title,
        location="Remote",
        description=description,
        source="fixture",
        source_url="https://example.test/job",
        apply_url="https://example.test/apply",
        ats_type="fixture",
        job_family=family,
        employment_type="FULL_TIME",
    )


def test_allows_entry_level_target_family():
    result = apply_hard_filters(make_job("Data Analyst", "Entry-level analytics role."), {"DATA_ANALYTICS"})
    assert result.allowed


def test_skips_senior_role():
    result = apply_hard_filters(make_job("Senior Data Analyst", "Analytics role."), {"DATA_ANALYTICS"})
    assert not result.allowed
    assert result.reason == "SENIORITY_TOO_HIGH"


def test_skips_us_citizen_only_role():
    result = apply_hard_filters(make_job("Data Analyst", "Applicants must be a U.S. citizen."), {"DATA_ANALYTICS"})
    assert not result.allowed
    assert result.reason == "US_CITIZEN_ONLY"

