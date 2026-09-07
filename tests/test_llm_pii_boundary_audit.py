"""Reviewer audit of the LLM candidate-fact boundary (Codex 4cf19be..1d8d6b9 + fact_selection WIP).

Structurally-sound parts (plain asserts): the fact selector only lets the model pick from a
fixed ID allowlist, withholds identity/contact/address/legal fact *values* unconditionally,
and fails closed to the deterministic selection on any schema deviation -> fabrication via this
path is not possible.

Gap (xfail): `llm.send_candidate_pii: false` in config/settings.yaml is surfaced to the operator
by `--llm-status` and the dashboard as a safety property, but no code path consults it. When
`llm.enabled` is flipped true with a key present, skill/project/education/experience fact VALUES
are sent to OpenAI regardless of the flag. Today `enabled: false` makes build_router return None
so it is latent, not live -- but the toggle gives false assurance.
"""
from __future__ import annotations

import pytest

from app.llm.fact_selection import LLMFactSelector, _allowed_facts
from app.llm.router import LLMRouter, ModelPrice, ProviderResult
from app.llm.runtime import build_router
from app.models.enums import JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateFact, CandidateProfile


class _Provider:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return ProviderResult(self.output, 100, 10)


def _job() -> Job:
    return Job(
        external_job_id="1", company_id="acme", company_name="Acme",
        title="Data Analyst", location="US",
        description="Requirements: SQL, dashboards.",
        source="greenhouse", source_url="u", apply_url="u", ats_type="greenhouse",
        job_family=JobFamily.DATA_ANALYTICS,
    )


def _profile() -> CandidateProfile:
    facts = {
        "name.full": CandidateFact("name.full", "identity", "Jane Doe"),
        "contact.email": CandidateFact("contact.email", "contact", "jane@example.com"),
        "contact.phone": CandidateFact("contact.phone", "contact", "555-0100"),
        "address.home": CandidateFact("address.home", "address", "1 Main St, Springfield"),
        "auth.status": CandidateFact("auth.status", "legal", "needs sponsorship"),
        "skill.sql": CandidateFact("skill.sql", "skill", "SQL"),
        "education.bs": CandidateFact("education.bs", "education", "B.S. Data Science, State U"),
    }
    return CandidateProfile("internal-test", 2, facts, {})


def _selector():
    provider = _Provider('{"selected_fact_ids":["skill.sql"]}')
    router = LLMRouter(provider, model_prices={"gpt-5-mini": ModelPrice(1, 1)})
    return LLMFactSelector(router), provider


# --------------------------------------------------------------- structural guarantees
def test_identity_contact_address_legal_values_are_withheld_from_the_model():
    allowed = _allowed_facts(
        _profile(),
        ["name.full", "contact.email", "contact.phone", "address.home", "auth.status",
         "skill.sql", "education.bs"],
    )
    assert set(allowed) == {"skill.sql", "education.bs"}
    for pii in ("Jane Doe", "jane@example.com", "555-0100", "1 Main St", "sponsorship"):
        assert pii not in repr(allowed)


def test_model_cannot_introduce_a_fact_id_outside_the_allowlist():
    provider = _Provider('{"selected_fact_ids":["experience.director_of_ai"]}')
    router = LLMRouter(provider, model_prices={"gpt-5-mini": ModelPrice(1, 1)})
    result = LLMFactSelector(router).select(
        job=_job(), profile=_profile(),
        candidate_fact_ids=["skill.sql", "education.bs"], stage0_passed=True,
    )
    assert result.selected_fact_ids == ["skill.sql", "education.bs"]  # fell back, no injection
    assert result.fallback_reason and result.fallback_reason.startswith("LLM_SELECTION_INVALID")


def test_prose_output_is_rejected_not_used_as_resume_text():
    provider = _Provider("Jane is a great fit; she led a $2M team.")
    router = LLMRouter(provider, model_prices={"gpt-5-mini": ModelPrice(1, 1)})
    result = LLMFactSelector(router).select(
        job=_job(), profile=_profile(), candidate_fact_ids=["skill.sql"], stage0_passed=True,
    )
    assert result.selected_fact_ids == ["skill.sql"]
    assert result.fallback_reason is not None


# --------------------------------------------------------------- the gap
@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1 (latent): llm.send_candidate_pii is display-only; build_router / LLMFactSelector never consult it, so skill/education/project/experience fact values reach OpenAI whenever llm.enabled is true")
def test_send_candidate_pii_false_prevents_fact_values_leaving_the_process():
    settings = {
        "llm": {
            "enabled": True, "provider": "openai",
            "cheap_model": "gpt-5-nano", "strong_model": "gpt-5-mini",
            "send_candidate_pii": False,
        }
    }
    # With a key present this returns a live router; the flag should either make it refuse
    # or force ID-only prompts. Right now it does neither.
    import os

    os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")
    router = build_router(settings)
    assert router is None, "send_candidate_pii=false should block the provider-backed selector"
