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


def test_skips_manager_title_for_newgrad_candidate():
    result = apply_hard_filters(
        make_job("Product Operations Manager", "Product operations role."),
        {"DATA_ANALYTICS"},
    )
    assert not result.allowed
    assert result.reason == "SENIORITY_TOO_HIGH"


def test_skips_us_citizen_only_role():
    result = apply_hard_filters(make_job("Data Analyst", "Applicants must be a U.S. citizen."), {"DATA_ANALYTICS"})
    assert not result.allowed
    assert result.reason == "US_CITIZEN_ONLY"


def test_no_sponsorship_depends_on_candidate_configuration():
    job = make_job("Data Analyst", "Candidates must be authorized to work in the U.S. without sponsorship.")
    allowed = apply_hard_filters(job, {"DATA_ANALYTICS"}, requires_visa_sponsorship=False)
    blocked = apply_hard_filters(job, {"DATA_ANALYTICS"}, requires_visa_sponsorship=True)
    incomplete = apply_hard_filters(job, {"DATA_ANALYTICS"}, requires_visa_sponsorship=None)

    assert allowed.allowed
    assert not blocked.allowed and blocked.reason == "NO_VISA_SPONSORSHIP"
    assert not incomplete.allowed and incomplete.reason == "WORK_AUTHORIZATION_PROFILE_INCOMPLETE"


def test_unknown_job_family_is_not_application_eligible():
    result = apply_hard_filters(make_job("Analyst", "Ambiguous but not disqualified.", JobFamily.UNKNOWN), {"DATA_ANALYTICS"})
    assert not result.allowed
    assert result.reason == "ROLE_CLASSIFICATION_REQUIRED"
