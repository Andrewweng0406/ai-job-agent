from __future__ import annotations

from dataclasses import dataclass, field


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

