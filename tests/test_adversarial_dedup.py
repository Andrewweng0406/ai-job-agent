"""Adversarial dedup tests. See docs/CLAUDE_REVIEW.md P1-3 and docs/FAILURE_MODEL.md ADV-11/12."""
from __future__ import annotations

import pytest

from app.normalization.deduplication import is_duplicate, job_identity_keys
from tests.adv_helpers import make_job


def test_exact_same_apply_url_is_duplicate():
    a = make_job(external_job_id="1", apply_url="https://boards.greenhouse.io/acme/jobs/1")
    b = make_job(external_job_id="2", source="ashby", apply_url="https://boards.greenhouse.io/acme/jobs/1")
    assert is_duplicate(b, job_identity_keys(a))


# ADV-12 ---------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="P1-3: apply_url tracking params not stripped before hashing")
def test_adv12_apply_url_tracking_params_are_ignored():
    # Same posting, different tracking URL, different source id, and a trivially
    # different description string (view counter / timestamp injected by the mirror).
    a = make_job(
        external_job_id="1",
        apply_url="https://job.example/acme/1",
        description="Build dashboards. SQL required.",
        company_name="Acme",
    )
    b = make_job(
        external_job_id="1b",
        apply_url="https://job.example/acme/1?gh_src=abc&utm_medium=x",
        description="Build dashboards. SQL required. (viewed 41 times)",
        company_name="Acme Inc",
    )
    assert is_duplicate(b, job_identity_keys(a))


# ADV-11 ---------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="P1-3: no requisition-number / normalized-location near-dedupe")
def test_adv11_same_req_via_two_sources_is_deduped():
    gh = make_job(
        external_job_id="gh-1",
        source="greenhouse",
        title="Data Analyst",
        location="New York, NY",
        description="Join the analytics team. Build dashboards. Requisition R-555.",
        apply_url="https://boards.greenhouse.io/acme/jobs/555",
    )
    mirror = make_job(
        external_job_id="acme-555",
        source="company_site",
        title="Data Analyst I",
        location="New York",
        description="Analytics team member. Dashboards and reporting. Job code 555.",
        apply_url="https://careers.acme.com/jobs/555",
    )
    # Only a shared normalized requisition number (555) links these; nothing else matches exactly.
    assert is_duplicate(mirror, job_identity_keys(gh))


def test_repost_with_new_id_identical_description_is_deduped():
    original = make_job(external_job_id="1", description="Analyze weekly retention. Build dashboards. SQL required.")
    repost = make_job(external_job_id="9999", description="Analyze weekly retention. Build dashboards. SQL required.")
    assert is_duplicate(repost, job_identity_keys(original))


@pytest.mark.xfail(strict=False, reason="P1-3: near-identical (not byte-identical) JD repost needs simhash, not exact hash")
def test_near_identical_repost_is_deduped():
    original = make_job(
        external_job_id="1",
        title="Data Analyst",
        description="Analyze weekly retention. Build dashboards. SQL required.",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    repost = make_job(
        external_job_id="9999",
        title="Data Analyst, Growth",
        description="Analyze weekly retention trends. Build dashboards. SQL required. Posted 2026-09.",
        apply_url="https://boards.greenhouse.io/acme/jobs/9999",
    )
    assert is_duplicate(repost, job_identity_keys(original))
