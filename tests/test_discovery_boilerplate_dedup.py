from app.normalization.deduplication import strong_job_identity_keys
from tests.adv_helpers import make_job


def test_shared_company_boilerplate_does_not_collapse_distinct_jobs():
    first = make_job(external_job_id="1", title="Data Analyst", location="San Francisco",
                     apply_url="https://jobs.example/1",
                     description="Join our mission. Build SQL dashboards for finance.")
    second = make_job(external_job_id="2", title="Software Engineer", location="New York",
                      apply_url="https://jobs.example/2",
                      description="Join our mission. Build Python services for customers.")
    assert strong_job_identity_keys(first).isdisjoint(strong_job_identity_keys(second))
