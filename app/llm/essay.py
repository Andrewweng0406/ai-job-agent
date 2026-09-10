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
from app.resumes.truth_validation import _number_supported

# Seniority / tenure claims a graduating student cannot truthfully make. Rejected
# wherever they appear (unless literally present in the candidate's own facts).
_HARD_OVERREACH_RE = re.compile(
    r"\byears?\s+of\s+(professional\s+|industry\s+|relevant\s+)?experience\b|"
    r"\b(a\s+)?decade\b|\bled\s+a\s+team\b|\bmanaged\s+(a\s+team|engineers|people|\d+)\b|"
    r"\b(senior|staff|principal|lead)\s+(engineer|scientist|analyst|developer)\b|"
    r"\bperformance reviews?\b|\bhiring (and firing|decisions)\b|"
    r"\bfull[- ]time (work )?experience\b",
    re.I,
)
# Company-scale language — fine only if it echoes the posting.
_SCALE_RE = re.compile(r"\b(millions?|billions?|at scale|enterprise|production systems?)\b", re.I)

_MAX_CHARS = 900
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})\b")

# proper nouns / acronyms that are always fine to mention
_ALLOWED_NOUNS = {
    "i", "i'm", "i've", "the", "my", "as", "at", "with", "in", "on", "and", "to",
    "python", "sql", "tableau", "power bi", "powerbi", "excel", "vba", "git", "github",
    "nlp", "llm", "llms", "arima", "ai", "ml", "us", "u.s.", "usa",
    "gtm", "saas", "api", "apis", "kpi", "kpis", "okr", "okrs", "b2b", "b2c",
    "etl", "ci/cd", "crm", "erp", "pnl", "p&l", "roi",
    # Ordinary sentence-initial evaluation language, not named entities.
    "success", "after", "before", "using", "through", "when", "while", "because",
    "instead", "overall", "finally", "first", "next", "then", "this", "these", "those",
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

    def answer_experience(self, *, question: str, role: str = "") -> EssayResult:
        """Draft an answer to a 'describe your experience / a time you…' prompt using
        only the candidate's real projects and roles. Same fabrication guards."""
        self._role_tokens = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9&.\-]+", role)}
        prompt = _experience_prompt(question, self._fact_texts)
        try:
            resp = self.router.complete(stage="3", model=self.model, prompt=prompt,
                                        stage0_passed=True, max_tokens=900)
        except (RuntimeError, ValueError) as exc:
            return EssayResult(False, reason=f"LLM_UNAVAILABLE:{str(exc).split(':', 1)[0]}")
        text = (resp.text or "").strip().strip('"')
        if len(text) < 40:
            return EssayResult(False, text=text, reason="ESSAY_TOO_SHORT")
        if len(text) > _MAX_CHARS + 300:
            return EssayResult(False, text=text, reason="ESSAY_TOO_LONG")
        facts_blob = " ".join(self._fact_texts).lower()
        hard = _HARD_OVERREACH_RE.search(text)
        if hard and hard.group(0).lower() not in facts_blob:
            return EssayResult(False, text=text, reason=f"ESSAY_OVERREACH:{hard.group(0).strip()}")
        for number in _NUMBER_RE.findall(text):
            if number.strip("%") in {"1", "2", "3"}:
                continue
            if not _number_supported(number, self._fact_texts):
                return EssayResult(False, text=text, reason=f"ESSAY_UNSUPPORTED_NUMBER:{number}")
        for noun in _PROPER_NOUN_RE.findall(text):
            n = noun.strip().lower()
            if n in _ALLOWED_NOUNS or n in self._role_tokens or len(n) <= 2:
                continue
            if any(n in a for a in self._allow) or any(a in n for a in self._allow):
                continue
            return EssayResult(False, text=text, reason=f"ESSAY_UNVERIFIED_ENTITY:{noun}")
        return EssayResult(True, text=text, used_model=self.model)

    def write(self, *, company: str, role: str, jd_excerpt: str, question: str) -> EssayResult:
        prompt = _prompt(company, role, jd_excerpt, question, self._fact_texts)
        # role-title tokens are not "unverified entities"
        self._role_tokens = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9&.\-]+", role)}
        try:
            resp = self.router.complete(stage="3", model=self.model, prompt=prompt,
                                        stage0_passed=True, max_tokens=900)
        except (RuntimeError, ValueError) as exc:
            return EssayResult(False, reason=f"LLM_UNAVAILABLE:{str(exc).split(':', 1)[0]}")
        text = (resp.text or "").strip().strip('"')
        verdict = self._validate(text, company, jd_excerpt)
        if verdict:
            return EssayResult(False, text=text, reason=verdict, used_model=self.model)
        return EssayResult(True, text=text, used_model=self.model)

    def _validate(self, text: str, company: str, jd: str) -> str | None:
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
        facts_blob = " ".join(self._fact_texts).lower()
        hard = _HARD_OVERREACH_RE.search(text)
        if hard and hard.group(0).lower() not in facts_blob:
            return f"ESSAY_OVERREACH:{hard.group(0).strip()}"
        for m in _SCALE_RE.findall(text):
            phrase = (m if isinstance(m, str) else m[0]).lower()
            if phrase not in jd.lower() and phrase not in facts_blob:
                return f"ESSAY_SCALE_CLAIM:{phrase}"
        role_tokens = getattr(self, "_role_tokens", set())
        for noun in _PROPER_NOUN_RE.findall(text):
            n = noun.strip().lower()
            if n in _ALLOWED_NOUNS or n in company.lower() or company.lower() in n:
                continue
            if all(tok in role_tokens or tok in _ALLOWED_NOUNS for tok in n.split()):
                continue
            if n in jd.lower():
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
        f"- Name {company} explicitly at least once.\n"
        "- Connect one or two candidate facts to something concrete in the role context.\n"
        "- Do NOT invent experience, employers, job titles, schools, coursework, metrics,\n"
        "  dates, tools, or commitments that are not in the facts above.\n"
        "- Do NOT claim years of experience, seniority, production systems, team management,\n"
        "  or external/enterprise scope.\n"
        "- Do NOT mention work authorization, visa status, salary, or start dates.\n"
        "- Output ONLY the answer text, no preamble, no quotes.\n"
    )


def _experience_prompt(question: str, fact_texts: list[str]) -> str:
    facts = "\n".join(f"- {t}" for t in fact_texts)
    return (
        "Draft the candidate's answer to this application question, in their own first-person voice.\n"
        f"QUESTION: {question}\n\n"
        "CANDIDATE FACTS — the ONLY experiences, projects, tools, and results you may use:\n"
        f"{facts}\n\n"
        "Rules:\n"
        "- 3 to 6 sentences. Concrete: name the project, what was done, what resulted.\n"
        "- Use ONLY facts above. Do NOT invent metrics, employers, titles, dates, team\n"
        "  sizes, tools, or outcomes. Do NOT claim seniority, production scale, or\n"
        "  managing people.\n"
        "- If the facts do not really cover the question, answer with the closest\n"
        "  genuine experience rather than inventing one.\n"
        "- Output ONLY the answer text.\n"
    )
