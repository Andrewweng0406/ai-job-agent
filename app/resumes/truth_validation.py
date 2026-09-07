from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TruthValidationResult:
    valid: bool
    unsupported_claims: list[str]


def validate_claims_against_profile(claims: list[str], supported_facts: list[str]) -> TruthValidationResult:
    normalized_facts = {fact.strip().lower() for fact in supported_facts if fact.strip()}
    unsupported = [claim for claim in claims if claim.strip().lower() not in normalized_facts]
    return TruthValidationResult(valid=not unsupported, unsupported_claims=unsupported)

