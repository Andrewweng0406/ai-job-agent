from app.models.enums import JobFamily
from app.models.job import Job
from app.normalization.deduplication import is_duplicate, job_identity_keys


def test_duplicate_detected_by_apply_url():
    job = Job(
        external_job_id="123",
        company_id="acme",
        company_name="Acme",
        title="Product Analyst",
        location="New York, NY",
        description="Entry-level product analytics.",
        source="greenhouse",
        source_url="https://example.test/jobs/123",
        apply_url="https://example.test/apply/123",
        ats_type="greenhouse",
        job_family=JobFamily.PRODUCT_PM,
    )
    seen = job_identity_keys(job)
    same_job = Job(
        external_job_id="456",
        company_id="acme",
        company_name="Acme",
        title="Product Analyst",
        location="New York, NY",
        description="Entry-level product analytics.",
        source="ashby",
        source_url="https://example.test/jobs/456",
        apply_url="https://example.test/apply/123",
        ats_type="ashby",
        job_family=JobFamily.PRODUCT_PM,
    )
    assert is_duplicate(same_job, seen)

