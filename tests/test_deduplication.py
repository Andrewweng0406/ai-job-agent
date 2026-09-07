from app.models.enums import JobFamily
from app.models.application import application_dedupe_key_for_job
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


def test_application_dedupe_key_uses_ats_requisition_key():
    first = Job(
        external_job_id="post-1",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="SQL",
        source="greenhouse",
        source_url="https://example.test/jobs/1",
        apply_url="https://example.test/apply/1",
        ats_type="greenhouse",
        job_family=JobFamily.DATA_ANALYTICS,
        metadata={"internal_job_id": "req-123"},
    )
    second = Job(
        external_job_id="post-2",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="SQL",
        source="greenhouse",
        source_url="https://example.test/jobs/2",
        apply_url="https://example.test/apply/2",
        ats_type="greenhouse",
        job_family=JobFamily.DATA_ANALYTICS,
        metadata={"internal_job_id": "req-123"},
    )

    assert application_dedupe_key_for_job(first, "cand_1") == application_dedupe_key_for_job(second, "cand_1")
