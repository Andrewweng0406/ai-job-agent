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
    r"share an example|example of a time|biggest challenge|a project you",
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
        return cls(values=values, rules=rules)

    def answer_key_for(self, label: str) -> str | None:
        low = " ".join((label or "").lower().split())
        for key, phrases in self.rules:
            if any(p in low for p in phrases):
                return key
        return None

    def resolve(self, label: str, options: list[str] | None = None) -> str | None:
        """Return the value to enter for `label`, mapped to an offered option when
        `options` is given. None means 'not covered — do not guess'."""
        key = self.answer_key_for(label)
        if key is None or key not in self.values:
            return None
        value = self.values[key]
        if not options:
            return value
        return _map_to_option(value, options)


_DECLINE_HINTS = ("decline", "prefer not", "don't wish", "do not wish", "rather not", "not disclose")


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
    best, score = None, 0
    for o, ol in opts:
        ow = {w for w in re.findall(r"[a-z]+", ol) if w not in stop}
        overlap = len(vw & ow)
        if overlap > score:
            best, score = o, overlap
    return best if score >= 3 else None
