import json

from app.llm.fact_selection import LLMFactSelector
from app.llm.router import LLMRouter, ModelPrice, ProviderResult
from app.models.enums import JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateFact, CandidateProfile


class _Provider:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return ProviderResult(self.output, 100, 10)


def _job():
    return Job(
        external_job_id="1", company_id="acme", company_name="Acme",
        title="Data Analyst", location="US",
        description="Benefits first. Requirements: SQL and dashboard experience.",
        source="greenhouse", source_url="u", apply_url="u", ats_type="greenhouse",
        job_family=JobFamily.DATA_ANALYTICS,
    )


def _profile():
    facts = {
        "name.full": CandidateFact("name.full", "identity", "Test User"),
        "contact.email": CandidateFact("contact.email", "contact", "test@example.com"),
        "auth.status": CandidateFact("auth.status", "legal", "authorized", literal_only=True),
        "skill.sql": CandidateFact("skill.sql", "skill", "SQL"),
        "project.dashboard": CandidateFact(
            "project.dashboard", "project", "Built a course dashboard with SQL"
        ),
    }
    return CandidateProfile("internal-test", 2, facts, {})


def _selector(output):
    provider = _Provider(output)
    router = LLMRouter(
        provider,
        model_prices={"gpt-5-nano": ModelPrice(1, 1)},
    )
    return LLMFactSelector(router), provider


def test_prompt_contains_only_allowed_non_pii_facts():
    selector, provider = _selector('{"selected_fact_ids":["skill.sql"]}')
    result = selector.select(
        job=_job(), profile=_profile(),
        candidate_fact_ids=["name.full", "contact.email", "auth.status", "skill.sql"],
        stage0_passed=True,
    )
    prompt = provider.calls[0]["prompt"]
    assert result.selected_fact_ids == ["skill.sql"]
    assert "skill.sql" in prompt and "SQL" in prompt
    assert "Test User" not in prompt
    assert "test@example.com" not in prompt
    assert "authorized" not in prompt
    assert "Benefits first" not in prompt


def test_unknown_fact_id_fails_closed_to_original_safe_selection():
    selector, _ = _selector('{"selected_fact_ids":["experience.fabricated"]}')
    result = selector.select(
        job=_job(), profile=_profile(),
        candidate_fact_ids=["skill.sql", "project.dashboard"],
        stage0_passed=True,
    )
    assert result.selected_fact_ids == ["skill.sql", "project.dashboard"]
    assert result.fallback_reason == "LLM_SELECTION_INVALID:ValueError"


def test_extra_output_keys_and_non_json_fail_closed():
    for output in (
        json.dumps({"selected_fact_ids": ["skill.sql"], "new_claim": "expert"}),
        "I recommend skill.sql",
    ):
        selector, _ = _selector(output)
        result = selector.select(
            job=_job(), profile=_profile(), candidate_fact_ids=["skill.sql"],
            stage0_passed=True,
        )
        assert result.selected_fact_ids == ["skill.sql"]
        assert result.fallback_reason is not None


def test_stage_zero_gate_still_blocks_provider_call():
    selector, provider = _selector('{"selected_fact_ids":[]}')
    try:
        selector.select(
            job=_job(), profile=_profile(), candidate_fact_ids=["skill.sql"],
            stage0_passed=False,
        )
    except RuntimeError as exc:
        assert "STAGE0" in str(exc)
    else:
        raise AssertionError("stage-zero gate did not block the provider")
    assert provider.calls == []


def test_provider_failure_falls_back_without_using_model_content():
    class FailedProvider:
        def complete(self, **_kwargs):
            raise RuntimeError("OPENAI_API_RESULT_UNKNOWN")

    selector = LLMFactSelector(LLMRouter(
        FailedProvider(), model_prices={"gpt-5-nano": ModelPrice(1, 1)}
    ))
    result = selector.select(
        job=_job(), profile=_profile(), candidate_fact_ids=["skill.sql"],
        stage0_passed=True,
    )
    assert result.selected_fact_ids == ["skill.sql"]
    assert result.fallback_reason == "LLM_PROVIDER_FALLBACK:OPENAI_API_RESULT_UNKNOWN"
