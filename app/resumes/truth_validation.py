from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.models.enums import QuestionAnswerState


@dataclass(frozen=True, slots=True)
class TruthValidationResult:
    valid: bool
    unsupported_claims: list[str]


@dataclass(frozen=True, slots=True)
class RequiredFieldsResult:
    valid: bool
    missing: list[str]


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    state: QuestionAnswerState
    answer: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceValidationResult:
    valid: bool
    unknown_fact_ids: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)


STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
}
LEGAL_QUESTION_PATTERN = re.compile(r"\b(immigration|visa|sponsorship|work authorization|authorized to work|citizenship)\b", re.I)
DATE_PATTERN = re.compile(r"\b(20\d{2}[-/]\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+20\d{2}|20\d{2})\b", re.I)
OVERREACH_PATTERN = re.compile(
    r"\b(production|millions?|professional|external clients?|institutional|managed a team|engineers?|"
    r"performance reviews?|hiring|senior|expert|expert-level|years of|full-time|company-wide|business units?)\b",
    re.I,
)


def validate_claims_against_profile(claims: list[str], supported_facts: list[str]) -> TruthValidationResult:
    unsupported = [claim for claim in claims if not _claim_supported(claim, supported_facts)]
    return TruthValidationResult(valid=not unsupported, unsupported_claims=unsupported)


def check_required_fields(resume_sections: dict[str, str], required_fact_ids: list[str]) -> RequiredFieldsResult:
    combined = "\n".join(resume_sections.values())
    missing: list[str] = []
    for fact_id in required_fact_ids:
        if fact_id.endswith(".grad_date"):
            present = bool(DATE_PATTERN.search(combined))
        elif fact_id.endswith(".school"):
            present = bool(re.search(r"\b(university|college|institute|school)\b", combined, re.I))
        elif fact_id.endswith(".degree"):
            present = bool(re.search(r"\b(b\.?s\.?|bachelor|m\.?s\.?|master|degree)\b", combined, re.I))
        else:
            present = fact_id.lower() in combined.lower()
        if not present:
            missing.append(fact_id)
    return RequiredFieldsResult(valid=not missing, missing=missing)


def answer_application_question(question: str, answer_bank: dict[str, str]) -> AnswerOutcome:
    if LEGAL_QUESTION_PATTERN.search(question):
        normalized_question = question.lower()
        if "detail" in normalized_question or "describe" in normalized_question or "restrictions" in normalized_question:
            return AnswerOutcome(QuestionAnswerState.HUMAN_REQUIRED, reason="LEGAL_OR_AUTHORIZATION_DETAIL_REQUIRED")
        if "sponsorship" in normalized_question and "requires_sponsorship_now_or_future" in answer_bank:
            return AnswerOutcome(QuestionAnswerState.AUTO_FROM_PROFILE, answer=answer_bank["requires_sponsorship_now_or_future"])
        if "authorized" in normalized_question and "work_authorized_us" in answer_bank:
            return AnswerOutcome(QuestionAnswerState.AUTO_FROM_PROFILE, answer=answer_bank["work_authorized_us"])
        return AnswerOutcome(QuestionAnswerState.HUMAN_REQUIRED, reason="UNKNOWN_LEGAL_OR_AUTHORIZATION_QUESTION")
    return AnswerOutcome(QuestionAnswerState.HUMAN_REQUIRED, reason="NO_CANONICAL_ANSWER_MAPPING")


def validate_with_provenance(items: list[dict[str, object]], profile_fact_ids: set[str]) -> ProvenanceValidationResult:
    unknown_ids: list[str] = []
    unsupported_numbers: list[str] = []
    unsupported_claims: list[str] = []
    for item in items:
        fact_ids = [str(fact_id) for fact_id in item.get("fact_ids", []) if str(fact_id)]
        text = str(item.get("text", ""))
        for fact_id in fact_ids:
            if fact_id not in profile_fact_ids:
                unknown_ids.append(fact_id)
        numbers = [str(number) for number in item.get("numbers", [])]
        if numbers:
            unsupported_numbers.extend(numbers)
        if OVERREACH_PATTERN.search(text):
            unsupported_claims.append(text)
        if not fact_ids:
            unsupported_claims.append(text)
    return ProvenanceValidationResult(
        valid=not unknown_ids and not unsupported_numbers and not unsupported_claims,
        unknown_fact_ids=unknown_ids,
        unsupported_numbers=unsupported_numbers,
        unsupported_claims=unsupported_claims,
    )


def _claim_supported(claim: str, supported_facts: list[str]) -> bool:
    normalized_claim = claim.strip().lower()
    if not normalized_claim:
        return True
    facts_blob = " ".join(fact.lower() for fact in supported_facts)
    if normalized_claim in facts_blob:
        return True
    claim_tokens = _meaningful_tokens(normalized_claim)
    if not claim_tokens:
        return True
    fact_tokens = _meaningful_tokens(facts_blob)
    overlap = claim_tokens & fact_tokens
    return len(overlap) / len(claim_tokens) >= 0.6


def _meaningful_tokens(value: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if token in STOPWORDS:
            continue
        if token.endswith("s") and len(token) > 3:
            token = token[:-1]
        tokens.add(token)
    return tokens
