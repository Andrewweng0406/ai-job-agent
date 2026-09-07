from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json


@dataclass(frozen=True, slots=True)
class ApplicationPreview:
    company: str
    role: str
    url: str
    persona: str | None
    resume_used: str | None
    fields_filled: dict[str, str] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)
    human_required_fields: list[str] = field(default_factory=list)
    validation_status: str = "PENDING"

    def to_markdown(self) -> str:
        lines = [
            f"# Application Preview - {self.company}",
            "",
            f"- Role: {self.role}",
            f"- URL: {self.url}",
            f"- Persona: {self.persona or 'TBD'}",
            f"- Resume used: {self.resume_used or 'None'}",
            f"- Validation status: {self.validation_status}",
            "",
            "## Fields Filled",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.fields_filled.items()))
        lines.append("")
        lines.append("## Answers")
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.answers.items()))
        lines.append("")
        lines.append("## Human Required")
        lines.extend(f"- {field}" for field in self.human_required_fields)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class AutofillPreview:
    transcript_id: str
    application_id: str
    approved_by: str
    fields: list[dict[str, str]]

    def to_markdown(self) -> str:
        lines = [
            f"# Autofill Preview - {self.transcript_id}",
            "",
            f"- Application: {self.application_id}",
            f"- Approved by: {self.approved_by}",
            "",
            "## Fields",
        ]
        lines.extend(f"- {field['selector']}: {field['value']}" for field in self.fields)
        return "\n".join(lines)


class ApprovedAutofillPreviewBuilder:
    def __init__(self, repository) -> None:
        self.repository = repository

    def build(self, transcript_id: str) -> AutofillPreview:
        row = self.repository.get_dry_run_transcript(transcript_id)
        if row is None:
            raise KeyError(f"Unknown transcript_id: {transcript_id}")
        if not row["approved_by"] or not row["approved_at"]:
            raise RuntimeError("Dry-run transcript is not approved")
        actual_hash = hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest()
        if actual_hash != row["payload_hash"]:
            raise RuntimeError("Dry-run transcript payload hash mismatch")
        if not row["would_submit"]:
            raise RuntimeError("Dry-run transcript is not submit-ready")
        payload = json.loads(row["payload_json"])
        fields = [
            {
                "label": str(field["label"]),
                "selector": str(field["selector"]),
                "value": str(field["value"]),
            }
            for field in payload.get("fields", [])
            if field.get("status") == "FILLED" and field.get("value") is not None
        ]
        return AutofillPreview(
            transcript_id=transcript_id,
            application_id=row["application_id"],
            approved_by=row["approved_by"],
            fields=fields,
        )
