"""Candidate's one-time answers to recurring application questions.

Used by the auto-apply loop AFTER profile-fact resolution and BEFORE routing a
required question to human review. A question the candidate has not pre-answered
here (and that no profile fact covers) is never guessed — it routes to review and
that application is not auto-submitted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.utils.config import load_yaml


# Free-text prompts that ask the candidate to *motivate / explain interest*.
# These go to the LLM essay path (verified facts only), not to a canned answer.
_ESSAY_RE = re.compile(
    r"why (do|are) you|why this (company|role|team)|why (join|work (here|at|for))|"
    r"what (interests|excites|draws) you|what (about|makes).{0,40}(interest|excit)|"
    r"tell us why|motivat(e|ion)|cover letter|what would you (bring|contribute)",
    re.I,
)

# Free-text prompts asking for a narrative about the candidate's real experience.
# The LLM may DRAFT these from verified facts; the human reviews before it is sent.
_EXPERIENCE_RE = re.compile(
    r"describe (a|your|an)|tell us about a time|tell us about your|walk us through|"
    r"give an example|provide an example|outline your experience|"
    r"what.{0,20}experience (do you have|with)|how have you|"
    r"share an example|example of a time|biggest challenge|a project you|"
    r"what.{0,40}\b(tools|technologies)\b.{0,80}(using|use|comfortable)|"
    r"which.{0,40}\b(tools|technologies)\b.{0,80}(using|use|comfortable)",
    re.I,
)

# Prompts that need a genuine artifact / reference / disclosure — never drafted,
# never auto-answered.
_MUST_QUEUE_RE = re.compile(
    r"writing sample|portfolio|references?|list (your|three|two)|"
    r"greatest (weakness|strength)|link to (your )?(github|portfolio|work)|"
    r"additional information|anything else (you|we should)|"
    r"arbitration|agree(ment)? to|acknowledge|consent to the|"
    r"policy for application|have you (ever )?(interviewed|applied|been employed)",
    re.I,
)


def is_essay_question(label: str) -> bool:
    return bool(_ESSAY_RE.search(label or ""))


def is_experience_question(label: str) -> bool:
    return bool(_EXPERIENCE_RE.search(label or "")) and not _MUST_QUEUE_RE.search(label or "")


def is_must_queue_question(label: str) -> bool:
    return bool(_MUST_QUEUE_RE.search(label or ""))


@dataclass(frozen=True, slots=True)
class StandardAnswers:
    values: dict[str, str]
    rules: list[tuple[str, tuple[str, ...]]]  # (answer_key, phrases)
    exact_approvals: tuple[tuple[str, str, str], ...] = ()  # company, normalized label, answer

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StandardAnswers":
        data = load_yaml(str(path)) or {}
        values = {str(k): str(v) for k, v in (data.get("answers") or {}).items()}
        rules: list[tuple[str, tuple[str, ...]]] = []
        for row in data.get("match") or []:
            key = str(row.get("key") or "")
            phrases = tuple(str(p).lower() for p in (row.get("phrases") or []))
            if key and phrases:
                rules.append((key, phrases))
        exact_approvals = []
        for row in data.get("approved_exact") or []:
            company = _normalize_exact(str(row.get("company") or ""))
            label = _normalize_exact(str(row.get("label") or ""))
            answer = str(row.get("answer") or "").strip()
            if company and label and answer:
                exact_approvals.append((company, label, answer))
        return cls(values=values, rules=rules, exact_approvals=tuple(exact_approvals))

    def resolve_exact(self, company: str, label: str, options: list[str] | None = None) -> str | None:
        """Resolve a candidate-approved answer only on exact company + prompt identity."""
        key = (_normalize_exact(company), _normalize_exact(label))
        matches = [answer for approved_company, approved_label, answer in self.exact_approvals
                   if (approved_company, approved_label) == key]
        if len(matches) != 1:
            return None
        return _map_answer(matches[0], options)

    def answer_key_for(self, label: str) -> str | None:
        low = " ".join(re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).split())
        # Prefer the narrow city answer over generic location rules. This matters
        # for autocomplete widgets, which often reject a full postal location.
        if re.search(r"\bcity\b", low) and any(key == "city" for key, _ in self.rules):
            return "city"
        for key, phrases in self.rules:
            normalized_phrases = (
                " ".join(re.sub(r"[^a-z0-9]+", " ", p).split()) for p in phrases
            )
            if any(p and p in low for p in normalized_phrases):
                return key
        return None

    def resolve(self, label: str, options: list[str] | None = None) -> str | None:
        """Return the value to enter for `label`, mapped to an offered option when
        `options` is given. None means 'not covered — do not guess'."""
        key = self.answer_key_for(label)
        if key is None or key not in self.values:
            return None
        value = self.values[key]
        return _map_answer(value, options)


def _normalize_exact(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _map_answer(value: str, options: list[str] | None) -> str | None:
    if not options:
        return value
    # Semicolon is the canonical multi-value delimiter. Commas occur inside
    # legitimate options such as "New York, NY" and must not split them.
    parts = [part.strip() for part in value.split(";") if part.strip()]
    if len(parts) <= 1:
        return _map_to_option(value, options)
    mapped = [_map_to_option(part, options) for part in parts]
    if any(part is None for part in mapped) or len(set(mapped)) != len(mapped):
        return None
    return "; ".join(part for part in mapped if part is not None)


_DECLINE_HINTS = (
    "decline", "prefer not", "don't wish", "do not wish", "rather not", "not disclose",
    "don't want to answer", "do not want to answer", "not want to answer",
    "wish not to answer", "choose not to", "prefer not to say", "not to self-identify",
    "i don't wish", "i do not wish",
)


def _map_to_option(value: str, options: list[str]) -> str | None:
    v = " ".join(value.strip().lower().split())
    opts = [(o, " ".join(o.strip().lower().split())) for o in options]

    for o, ol in opts:                       # exact
        if ol == v:
            return o
    if v in {"yes", "no"}:                   # yes/no
        for o, ol in opts:
            if ol == v or ol.startswith(v + " ") or ol.startswith(v + ",") or ol.startswith(v + "."):
                return o
    if any(h in v for h in _DECLINE_HINTS):  # decline-to-answer family
        for o, ol in opts:
            if any(h in ol for h in _DECLINE_HINTS):
                return o
    for o, ol in opts:                       # containment either way
        if v in ol or ol in v:
            return o
    for anchor in ("never", "currently", "previously", "not applicable", "none"):
        if anchor in v:
            hits = [o for o, ol in opts if anchor in ol]
            if len(hits) == 1:
                return hits[0]
    # strongest word overlap (for phrased options like the "have you worked here" set)
    stop = {"i", "a", "an", "the", "to", "of", "at", "in", "or", "and", "for", "as", "have", "has", "you", "your", "any"}
    vw = {w for w in re.findall(r"[a-z]+", v) if w not in stop}
    best, score = None, 0.0

    def _sim(a: set[str], b: set[str]) -> float:
        s = 0.0
        for x in a:
            if x in b:
                s += 1
            elif any(len(x) >= 5 and (x.startswith(y) or y.startswith(x)) for y in b):
                s += 0.8  # bachelor / bachelors, analytic / analytics
        return s

    for o, ol in opts:
        ow = {w for w in re.findall(r"[a-z]+", ol) if w not in stop}
        sc = _sim(vw, ow)
        if sc > score:
            best, score = o, sc
    if score >= 3:
        return best
    if best is not None and score >= 1.6 and len(vw) <= 3:
        return best
    # exactly one option shares a distinctive stem with a short answer
    if len(vw) <= 3:
        distinctive = {w for w in vw if len(w) >= 5}
        hits = [o for o, ol in opts
                if any(d in ol or any(t.startswith(d[:5]) or d.startswith(t[:5])
                                      for t in re.findall(r"[a-z]+", ol) if len(t) >= 5)
                       for d in distinctive)]
        if len(hits) == 1:
            return hits[0]
    return None
