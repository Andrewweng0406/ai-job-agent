"""LLM-written short 'why this company / role' answers, constrained to verified facts.

The model may only express motivation and fit using (a) the candidate's own profile
facts and (b) the company/role text supplied. A generated answer is rejected if it
introduces a number, employer, school, credential, or seniority claim not present in
the profile. Rejected -> the question routes to human review and the application is
not auto-submitted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.llm.router import LLMRouter
from app.resumes.profile import CandidateProfile
from app.resumes.truth_validation import OVERREACH_PATTERN, _number_supported

_MAX_CHARS = 900
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})\b")

# proper nouns that are always fine to mention
_ALLOWED_NOUNS = {
    "i", "i'm", "the", "my", "as", "at", "with", "python", "sql", "tableau",
    "power bi", "git", "github", "nlp", "llm", "arima", "ai", "us",
}


@dataclass(frozen=True, slots=True)
class EssayResult:
    ok: bool
    text: str = ""
    reason: str | None = None
    used_model: str | None = None


class EssayWriter:
    def __init__(self, router: LLMRouter, profile: CandidateProfile, *, model: str = "gpt-5-mini") -> None:
        self.router = router
        self.profile = profile
        self.model = model
        self._fact_texts = [str(f.value) for f in profile.facts.values() if not f.is_missing]
        self._allow = _build_allowlist(self._fact_texts)

    def write(self, *, company: str, role: str, jd_excerpt: str, question: str) -> EssayResult:
        prompt = _prompt(company, role, jd_excerpt, question, self._fact_texts)
        try:
            resp = self.router.complete(stage="3", model=self.model, prompt=prompt,
                                        stage0_passed=True, max_tokens=280)
        except (RuntimeError, ValueError) as exc:
            return EssayResult(False, reason=f"LLM_UNAVAILABLE:{str(exc).split(':', 1)[0]}")
        text = (resp.text or "").strip().strip('"')
        verdict = self._validate(text, company)
        if verdict:
            return EssayResult(False, text=text, reason=verdict, used_model=self.model)
        return EssayResult(True, text=text, used_model=self.model)

    def _validate(self, text: str, company: str) -> str | None:
        if not text or len(text) < 40:
            return "ESSAY_TOO_SHORT"
        if len(text) > _MAX_CHARS:
            return "ESSAY_TOO_LONG"
        if company.split()[0].lower() not in text.lower():
            return "ESSAY_OFF_TOPIC"
        for number in _NUMBER_RE.findall(text):
            if number.strip("%") in {"1", "2", "3"}:  # ordinals / trivial
                continue
            if not _number_supported(number, self._fact_texts):
                return f"ESSAY_UNSUPPORTED_NUMBER:{number}"
        for m in OVERREACH_PATTERN.findall(text):
            phrase = m if isinstance(m, str) else m[0]
            if phrase and not any(phrase.lower() in ft.lower() for ft in self._fact_texts):
                return f"ESSAY_OVERREACH:{phrase}"
        for noun in _PROPER_NOUN_RE.findall(text):
            n = noun.strip().lower()
            if n in _ALLOWED_NOUNS or n in company.lower() or company.lower() in n:
                continue
            if any(n in a for a in self._allow) or any(a in n for a in self._allow):
                continue
            if len(n) <= 2:
                continue
            return f"ESSAY_UNVERIFIED_ENTITY:{noun}"
        return None


def _build_allowlist(fact_texts: list[str]) -> set[str]:
    allow: set[str] = set(_ALLOWED_NOUNS)
    for ft in fact_texts:
        for m in _PROPER_NOUN_RE.findall(ft):
            allow.add(m.strip().lower())
        allow.add(ft.strip().lower())
    return allow


def _prompt(company: str, role: str, jd: str, question: str, fact_texts: list[str]) -> str:
    facts = "\n".join(f"- {t}" for t in fact_texts)
    return (
        "You are helping a candidate answer one application question in their own voice.\n"
        f"COMPANY: {company}\nROLE: {role}\n"
        f"ROLE CONTEXT (from the posting):\n{jd[:1500]}\n\n"
        f"THE QUESTION: {question}\n\n"
        "CANDIDATE FACTS — the ONLY things you may say about the candidate:\n"
        f"{facts}\n\n"
        "Rules:\n"
        "- 3 to 5 sentences, first person, specific, no clichés, no flattery padding.\n"
        "- Connect one or two candidate facts to something concrete in the role context.\n"
        "- Do NOT invent experience, employers, job titles, schools, coursework, metrics,\n"
        "  dates, tools, or commitments that are not in the facts above.\n"
        "- Do NOT claim years of experience, seniority, production systems, team management,\n"
        "  or external/enterprise scope.\n"
        "- Output ONLY the answer text, no preamble, no quotes.\n"
    )
