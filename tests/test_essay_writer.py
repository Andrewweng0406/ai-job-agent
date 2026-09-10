"""EssayWriter: the model may only express motivation using verified profile facts.
Anything it invents (numbers, employers, seniority, credentials) is rejected and the
question is not auto-answered.
"""
from __future__ import annotations

import pytest

from app.llm.essay import EssayWriter
from app.llm.router import LLMRouter, ModelPrice, ProviderResult
from app.resumes.profile import CandidateFact, CandidateProfile


class _Provider:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kw):
        self.calls.append(kw)
        return ProviderResult(self.text, 200, 60)


def _profile():
    facts = {
        "edu.school": CandidateFact("edu.school", "education", "San Jose State University"),
        "edu.degree": CandidateFact("edu.degree", "education", "B.S. in Data Science"),
        "proj.radar": CandidateFact("proj.radar", "project",
                                    "Built an NLP pipeline that parses earnings transcripts across 50+ tech stocks."),
        "skill.py": CandidateFact("skill.py", "skill", "Python, SQL, Tableau"),
    }
    return CandidateProfile("internal-test", 2, facts, {})


def _writer(text):
    p = _Provider(text)
    r = LLMRouter(p, model_prices={"gpt-5-mini": ModelPrice(1, 1)})
    return EssayWriter(r, _profile(), model="gpt-5-mini"), p


JD = "You will build data pipelines and analytics for the payments team using Python and SQL."


def test_clean_grounded_answer_is_accepted():
    text = ("I've spent the last year building an NLP pipeline that parses earnings transcripts "
            "across 50+ tech stocks, and Stripe's payments analytics work is exactly that kind of "
            "problem at a much larger scale. I work day to day in Python and SQL, the same stack "
            "your team uses. My Data Science degree at San Jose State has been very hands-on. "
            "I'd be excited to bring that to the payments team.")
    w, p = _writer(text)
    res = w.write(company="Stripe", role="Data Analyst", jd_excerpt=JD, question="Why Stripe?")
    assert res.ok, res.reason
    assert p.calls and "San Jose State University" in p.calls[0]["prompt"]


def test_invented_employer_is_rejected():
    w, _ = _writer("My time at Google taught me a lot, and Stripe would be an exciting next chapter "
                   "for me given my Python background and interest in payments infrastructure.")
    res = w.write(company="Stripe", role="Data Analyst", jd_excerpt=JD, question="Why Stripe?")
    assert not res.ok
    assert res.reason.startswith("ESSAY_UNVERIFIED_ENTITY")


def test_invented_metric_is_rejected():
    w, _ = _writer("At San Jose State I improved model accuracy by 47% and shipped to 3 million users. "
                   "Stripe would be a great next step for me and my Python background.")
    res = w.write(company="Stripe", role="Data Analyst", jd_excerpt=JD, question="Why Stripe?")
    assert not res.ok
    assert res.reason.startswith("ESSAY_UNSUPPORTED_NUMBER") or res.reason.startswith("ESSAY_OVERREACH")


def test_seniority_overreach_is_rejected():
    w, _ = _writer("With years of experience managing a team of senior engineers on company-wide "
                   "production systems, I think Stripe is the right place for me and my SQL skills.")
    res = w.write(company="Stripe", role="Data Analyst", jd_excerpt=JD, question="Why Stripe?")
    assert not res.ok
    assert res.reason.startswith("ESSAY_OVERREACH")


def test_off_topic_answer_is_rejected():
    w, _ = _writer("I really enjoy Python and SQL and building dashboards for fun on weekends. "
                   "Data science is my passion and I hope to keep learning every single day here.")
    res = w.write(company="Databricks", role="Analyst", jd_excerpt=JD, question="Why Databricks?")
    assert not res.ok
    assert res.reason == "ESSAY_OFF_TOPIC"


def test_provider_failure_is_reported_not_raised():
    class Boom:
        def complete(self, **kw):
            raise RuntimeError("OPENAI_API_RESULT_UNKNOWN")

    r = LLMRouter(Boom(), model_prices={"gpt-5-mini": ModelPrice(1, 1)})
    res = EssayWriter(r, _profile()).write(company="Stripe", role="x", jd_excerpt=JD, question="Why?")
    assert not res.ok and res.reason.startswith("LLM_UNAVAILABLE")


def test_sentence_initial_success_is_not_treated_as_an_entity():
    text = (
        "I built an NLP pipeline that parses earnings transcripts across 50+ tech stocks. "
        "Success was measured by whether the pipeline consistently extracted the financial metrics "
        "needed for analysis. I used Python and SQL to turn those results into a clearer workflow."
    )
    writer, _ = _writer(text)

    result = writer.answer_experience(
        question="How did you use data to improve a product and measure success?",
        role="Product Operations Specialist",
    )

    assert result.ok, result.reason


def test_sentence_initial_transition_word_is_not_treated_as_an_entity():
    text = (
        "I built an NLP pipeline that parses earnings transcripts across 50+ tech stocks. "
        "After reviewing the extracted metrics, I used Python and SQL to improve the analysis workflow. "
        "Success was measured by whether the pipeline consistently produced the inputs needed for analysis."
    )
    writer, _ = _writer(text)

    result = writer.answer_experience(question="How did you improve a product?", role="Analyst")

    assert result.ok, result.reason
