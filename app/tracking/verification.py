from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.models.enums import ApplicationStatus


class EvidenceTier(StrEnum):
    T1_CONFIRMATION_ID = "T1"
    T2_BACKEND_SUCCESS = "T2"
    T3_CONFIRMATION_EMAIL = "T3"
    T4_PORTAL_ENTRY = "T4"
    T5_WEAK_PAGE_TEXT = "T5"


STRONG_EVIDENCE_TIERS = {
    EvidenceTier.T1_CONFIRMATION_ID,
    EvidenceTier.T2_BACKEND_SUCCESS,
    EvidenceTier.T3_CONFIRMATION_EMAIL,
    EvidenceTier.T4_PORTAL_ENTRY,
}


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    tier: EvidenceTier
    source: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmation_id: str | None = None
    backend_ref: str | None = None
    email_message_id: str | None = None
    portal_seen_at: str | None = None
    success_page_screenshot: str | None = None
    success_page_text_match: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_strong(self) -> bool:
        return self.tier in STRONG_EVIDENCE_TIERS

    def to_confirmation_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "tier": self.tier.value,
            "source": self.source,
            "verified_at": self.captured_at.isoformat(),
        }
        for key in (
            "confirmation_id",
            "backend_ref",
            "email_message_id",
            "portal_seen_at",
            "success_page_screenshot",
            "success_page_text_match",
        ):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.metadata:
            data["metadata"] = self.metadata
        return data


class VerificationService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def record_evidence(self, application_id: str, evidence: VerificationEvidence) -> ApplicationStatus:
        if not evidence.is_strong():
            self.repository.merge_confirmation_data(application_id, evidence.to_confirmation_data())
            return ApplicationStatus.SUBMITTED

        current = self.repository.get_application_status(application_id)
        if current not in {ApplicationStatus.SUBMITTED, ApplicationStatus.SUBMISSION_UNKNOWN}:
            raise ValueError(f"Cannot verify application from state {current}")
        self.repository.merge_confirmation_data(application_id, evidence.to_confirmation_data())
        self.repository.transition_application(application_id, ApplicationStatus.VERIFIED, f"verified via evidence tier {evidence.tier.value}")
        self.repository.set_submission_verified_at(application_id, evidence.captured_at)
        return ApplicationStatus.VERIFIED

