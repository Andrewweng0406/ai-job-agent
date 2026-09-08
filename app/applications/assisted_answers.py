"""Load and validate the human's answers + approval for an assisted-apply packet.

The human writes `answers.yaml`:

    approved_by: andrew
    approved_at: 2026-09-08T10:00:00-07:00
    answers:
      q3: "United States"
      q4: "New York, NY"
      q7: "I'm drawn to Verkada's ..."

Every REQUIRED open question in the packet must have a non-empty answer, and the
approval fields must be present, or `load_answers` raises. Nothing here submits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.applications.review_packet import ReviewPacket
from app.utils.config import load_yaml


class AnswersError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedAnswers:
    approved_by: str
    approved_at: str
    answers: dict[str, str]  # field_id -> answer

    def selector_values(self, packet: ReviewPacket, raw_field_selectors: dict[str, str]) -> dict[str, str]:
        """Map field_id answers onto DOM selectors using the packet's question order."""
        out: dict[str, str] = {}
        for q in packet.needs_your_answer:
            if q.field_id in self.answers:
                selector = raw_field_selectors.get(q.field_id)
                if selector:
                    out[selector] = self.answers[q.field_id]
        return out


def load_answers(path: str | Path, packet: ReviewPacket) -> ApprovedAnswers:
    data: dict[str, Any] = load_yaml(str(path))
    if not isinstance(data, dict):
        raise AnswersError("answers file is not a mapping")

    approved_by = str(data.get("approved_by") or "").strip()
    approved_at = str(data.get("approved_at") or "").strip()
    if not approved_by:
        raise AnswersError("answers.yaml: missing approved_by")
    try:
        datetime.fromisoformat(approved_at)
    except ValueError as exc:
        raise AnswersError(f"answers.yaml: approved_at is not ISO-8601: {approved_at!r}") from exc

    answers = data.get("answers") or {}
    if not isinstance(answers, dict):
        raise AnswersError("answers.yaml: 'answers' must be a mapping of field_id -> answer")
    answers = {str(k): str(v).strip() for k, v in answers.items()}

    if packet.blocked:
        raise AnswersError(
            "packet has BLOCKED fields that cannot be answered here: "
            + ", ".join(q.label for q in packet.blocked)
        )

    required_ids = {q.field_id for q in packet.needs_your_answer if q.required}
    missing = sorted(fid for fid in required_ids if not answers.get(fid))
    if missing:
        labels = {q.field_id: q.label for q in packet.needs_your_answer}
        raise AnswersError(
            "answers.yaml is missing required answers:\n"
            + "\n".join(f"  {fid}: {labels.get(fid, '?')}" for fid in missing)
        )

    known = {q.field_id for q in packet.needs_your_answer}
    unknown = sorted(set(answers) - known)
    if unknown:
        raise AnswersError(f"answers.yaml has answers for unknown field_ids: {unknown}")

    # Validate option-constrained answers.
    by_id = {q.field_id: q for q in packet.needs_your_answer}
    for fid, value in answers.items():
        q = by_id[fid]
        if q.options and value and value not in q.options:
            raise AnswersError(
                f"answers.yaml[{fid}] = {value!r} is not one of the allowed options: {q.options}"
            )

    return ApprovedAnswers(approved_by=approved_by, approved_at=approved_at, answers=answers)
