from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from app.models.enums import QuestionAnswerState
from app.resumes.profile import CandidateProfile


class FieldPolicy(StrEnum):
    AUTO_SAFE = "AUTO_SAFE"
    PROFILE_REQUIRED = "PROFILE_REQUIRED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    NEVER_GUESS = "NEVER_GUESS"
    OPTIONAL_SKIP = "OPTIONAL_SKIP"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    canonical_key: str
    policy: FieldPolicy
    fact_id: str | None = None
    answer_key: str | None = None
    constant: str | None = None


@dataclass(frozen=True, slots=True)
class ResolveResult:
    state: QuestionAnswerState
    value: str | None = None
    reason: str | None = None


FIELD_SPECS = {
    "full_name": FieldSpec("full_name", FieldPolicy.PROFILE_REQUIRED, fact_id="name.full"),
    "first_name": FieldSpec("personal.first_name", FieldPolicy.PROFILE_REQUIRED, fact_id="name.full"),
    "last_name": FieldSpec("personal.last_name", FieldPolicy.PROFILE_REQUIRED, fact_id="name.full"),
    "email": FieldSpec("email", FieldPolicy.PROFILE_REQUIRED, fact_id="contact.email"),
    "phone": FieldSpec("phone", FieldPolicy.PROFILE_REQUIRED, fact_id="contact.phone"),
    "school": FieldSpec("school", FieldPolicy.PROFILE_REQUIRED, fact_id="edu.primary.school"),
    "graduation_date": FieldSpec("graduation_date", FieldPolicy.PROFILE_REQUIRED, fact_id="edu.primary.grad_date"),
    "linkedin": FieldSpec("application.linkedin_url", FieldPolicy.OPTIONAL_SKIP, fact_id="links.linkedin"),
    "github": FieldSpec("application.github_url", FieldPolicy.OPTIONAL_SKIP, fact_id="links.github"),
    "resume": FieldSpec("application.resume", FieldPolicy.PROFILE_REQUIRED),
    "cover_letter": FieldSpec("application.cover_letter", FieldPolicy.OPTIONAL_SKIP),
    "work_authorized_us": FieldSpec(
        "work_authorized_us",
        FieldPolicy.NEVER_GUESS,
        answer_key="work_authorized_us",
    ),
    "requires_sponsorship": FieldSpec(
        "requires_sponsorship",
        FieldPolicy.NEVER_GUESS,
        answer_key="requires_sponsorship_now_or_future",
    ),
    "eeo_decline": FieldSpec("eeo_decline", FieldPolicy.NEVER_GUESS, constant="Decline to self-identify"),
    "source": FieldSpec("source", FieldPolicy.AUTO_SAFE, constant="Company website"),
}


def classify_label(raw_label: str, options: list[str] | None = None) -> FieldSpec | None:
    label = " ".join(raw_label.lower().split())
    if re.search(r"\b(immigration|visa|sponsorship|citizen|authorized to work|work authorization|employer support|petition|contingent on employer action)\b", label):
        if _is_known_sponsorship_question(label):
            return FIELD_SPECS["requires_sponsorship"]
        if _is_known_authorization_question(label):
            return FIELD_SPECS["work_authorized_us"]
        return FieldSpec("legal_unknown", FieldPolicy.HUMAN_REQUIRED)
    if re.search(r"\b(gender|race|ethnicity|veteran|disability)\b", label):
        return FIELD_SPECS["eeo_decline"]
    if "cover letter" in label:
        return FIELD_SPECS["cover_letter"]
    if "resume" in label or "cv" in label:
        return FIELD_SPECS["resume"]
    if "linkedin" in label:
        return FIELD_SPECS["linkedin"]
    if "github" in label:
        return FIELD_SPECS["github"]
    if "email" in label:
        return FIELD_SPECS["email"]
    if "phone" in label:
        return FIELD_SPECS["phone"]
    if "first name" in label or label == "given name":
        return FIELD_SPECS["first_name"]
    if "last name" in label or label == "surname" or label == "family name":
        return FIELD_SPECS["last_name"]
    if "full name" in label or label == "name":
        return FIELD_SPECS["full_name"]
    if "school" in label or "university" in label:
        return FIELD_SPECS["school"]
    if "graduation" in label or "expected completion" in label:
        return FIELD_SPECS["graduation_date"]
    if "how did you hear" in label or re.search(r"\b(source|referral source)\b", label) and not re.search(r"\b(open source|source code|source of .*experience)\b", label):
        return FIELD_SPECS["source"]
    return None


def _is_known_authorization_question(label: str) -> bool:
    return bool(re.search(r"\b(legally\s+)?authorized\s+to\s+work\s+in\s+(the\s+)?(u\.s\.|us|united states)\b", label))


def _is_known_sponsorship_question(label: str) -> bool:
    if "cannot" in label or "can't" in label or "unable" in label:
        return False
    return bool(
        re.search(r"\b(now\s+or\s+in\s+the\s+future|current\s+or\s+future)\b", label)
        and re.search(r"\brequire\s+(visa\s+|employment\s+visa\s+)?sponsorship\b|\bsponsorship\s+for\s+an\s+employment\s+visa\b", label)
    )


def resolve_value(spec: FieldSpec, profile: CandidateProfile) -> ResolveResult:
    if spec.policy == FieldPolicy.HUMAN_REQUIRED:
        return ResolveResult(QuestionAnswerState.HUMAN_REQUIRED, reason="FIELD_REQUIRES_HUMAN")
    if spec.policy == FieldPolicy.OPTIONAL_SKIP:
        if spec.fact_id:
            fact = profile.facts.get(spec.fact_id)
            if fact is not None and not fact.is_missing:
                return ResolveResult(QuestionAnswerState.AUTO_FROM_PROFILE, value=str(fact.value))
        return ResolveResult(QuestionAnswerState.UNSUPPORTED, reason="OPTIONAL_SKIP")
    if spec.constant is not None:
        return ResolveResult(QuestionAnswerState.AUTO_SAFE, value=spec.constant)
    if spec.answer_key is not None:
        value = profile.application_answers.get(spec.answer_key)
        if value:
            return ResolveResult(QuestionAnswerState.AUTO_FROM_PROFILE, value=value)
        return ResolveResult(QuestionAnswerState.HUMAN_REQUIRED, reason=f"MISSING_CANONICAL_ANSWER:{spec.answer_key}")
    if spec.fact_id is not None:
        fact = profile.facts.get(spec.fact_id)
        if fact is None or fact.is_missing:
            return ResolveResult(QuestionAnswerState.HUMAN_REQUIRED, reason=f"PROFILE_INCOMPLETE:{spec.fact_id}")
        if spec.canonical_key == "personal.first_name":
            return ResolveResult(QuestionAnswerState.AUTO_FROM_PROFILE, value=str(fact.value).split()[0])
        if spec.canonical_key == "personal.last_name":
            parts = str(fact.value).split()
            if len(parts) <= 1:
                return ResolveResult(QuestionAnswerState.HUMAN_REQUIRED, reason="PROFILE_INCOMPLETE:name.full")
            return ResolveResult(QuestionAnswerState.AUTO_FROM_PROFILE, value=parts[-1])
        return ResolveResult(QuestionAnswerState.AUTO_FROM_PROFILE, value=str(fact.value))
    return ResolveResult(QuestionAnswerState.UNSUPPORTED, reason="NO_RESOLUTION_RULE")
