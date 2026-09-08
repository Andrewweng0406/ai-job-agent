from app.models.enums import JobFamily
from app.models.application import application_dedupe_key_for_job
from app.models.job import Job
from app.normalization.deduplication import is_duplicate, job_identity_keys
from app.database.repository import JobAgentRepository
from app.models.application import Application


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


def test_placeholder_requisition_id_does_not_merge_distinct_greenhouse_jobs():
    def job(external_id, internal_id):
        return Job(
            external_job_id=external_id, company_id="stripe", company_name="Stripe",
            title="Data Analyst", location="US", description="SQL", source="greenhouse",
            source_url=f"https://stripe.com/jobs/search?gh_jid={external_id}",
            apply_url=f"https://stripe.com/jobs/search?gh_jid={external_id}",
            ats_type="greenhouse", job_family=JobFamily.DATA_ANALYTICS,
            metadata={"requisition_id": "See Opening ID", "internal_job_id": internal_id},
        )

    first = job("8172487", "3537052")
    second = job("8172508", "3537062")
    assert application_dedupe_key_for_job(first, "cand_1") != application_dedupe_key_for_job(second, "cand_1")


def test_legacy_repository_job_id_guard_prevents_duplicate_application(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job = Job(
        external_job_id="1", company_id="acme", company_name="Acme",
        title="Data Analyst", location="US", description="SQL", source="greenhouse",
        source_url="https://example.test/jobs/1", apply_url="https://example.test/jobs/1",
        ats_type="greenhouse", job_family=JobFamily.DATA_ANALYTICS,
    )
    job_id = repo.upsert_job(job)
    first = Application(job_id, "Acme", "Data Analyst", "US", JobFamily.DATA_ANALYTICS,
                        "greenhouse", "greenhouse", dedupe_key="first")
    second = Application(job_id, "Acme", "Data Analyst", "US", JobFamily.DATA_ANALYTICS,
                         "greenhouse", "greenhouse", dedupe_key="second")
    assert repo.insert_application(first) == first.application_id
    assert repo.insert_application(second) == first.application_id
    with repo.connect() as connection:
        assert connection.execute("SELECT count(*) FROM applications").fetchone()[0] == 1
