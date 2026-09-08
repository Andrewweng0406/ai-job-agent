"""Per-application review packet for the human-in-the-loop assisted-apply flow.

A packet is what a human reviews before any submission: the profile-safe fields the
agent would pre-fill, and the required questions the agent will NOT answer on its own
(judgment / legal / free-text). The human answers those, approves, and only then does
the assisted-fill step run — and even then the final Submit click is the human's.

Pure data transformation — no browser, no network — so it is unit-testable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.applications.form_engine import FormFieldResolution, FormFieldStatus, RawFormField


# Why a given required field is left to the human.
_REASON_HELP = {
    "FORM_MAPPING": "No profile fact maps to this field — the agent will not guess.",
    "HUMAN_REQUIRED": "Judgment / free-text answer the agent must not write for you.",
    "NEVER_GUESS": "Legal / sensitive — must be answered by you explicitly.",
    "PROFILE_INCOMPLETE": "Your profile is missing the fact this needs.",
    "TRUTH_VALIDATION_FAILED": "Resume artifact failed validation; upload is blocked.",
}


@dataclass(frozen=True, slots=True)
class SafeField:
    label: str
    canonical_key: str | None
    kind: str
    provenance: dict[str, str]
    # never the raw value — a short, non-sensitive hint only
    value_hint: str


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    field_id: str
    label: str
    kind: str
    options: list[str]
    required: bool
    why: str


@dataclass(frozen=True, slots=True)
class ReviewPacket:
    company: str
    role: str
    apply_url: str
    ats: str
    safe_prefill: list[SafeField]
    needs_your_answer: list[OpenQuestion]
    optional_skipped: int
    blocked: list[OpenQuestion]
    resume_fact_ids: list[str] = field(default_factory=list)

    @property
    def ready_for_assisted_fill(self) -> bool:
        """True only once every required open question has somewhere to get an answer."""
        return not self.blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "role": self.role,
            "apply_url": self.apply_url,
            "ats": self.ats,
            "safe_prefill": [asdict(s) for s in self.safe_prefill],
            "needs_your_answer": [asdict(q) for q in self.needs_your_answer],
            "optional_skipped": self.optional_skipped,
            "blocked": [asdict(q) for q in self.blocked],
            "resume_fact_ids": list(self.resume_fact_ids),
            "ready_for_assisted_fill": self.ready_for_assisted_fill,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Review packet — {self.role} @ {self.company}",
            "",
            f"- Apply URL: {self.apply_url}",
            f"- ATS: {self.ats}",
            f"- Optional fields the agent will skip: {self.optional_skipped}",
            "",
            "## The agent will pre-fill these from your profile",
            "",
        ]
        if self.safe_prefill:
            for s in self.safe_prefill:
                src = ", ".join(f"{k}={v}" for k, v in s.provenance.items()) or "profile"
                lines.append(f"- **{s.label}** ({s.canonical_key or s.kind}) — from {src} — e.g. `{s.value_hint}`")
        else:
            lines.append("- _(none)_")
        lines += ["", "## You must answer these — the agent will NOT", ""]
        if self.needs_your_answer:
            for q in self.needs_your_answer:
                opt = f" — options: {', '.join(q.options)}" if q.options else ""
                lines.append(f"- [`{q.field_id}`] **{q.label}** ({q.kind}){opt}")
                lines.append(f"    - {q.why}")
        else:
            lines.append("- _(none — every required field maps to your profile)_")
        if self.blocked:
            lines += ["", "## Blocked — cannot proceed until resolved", ""]
            for q in self.blocked:
                lines.append(f"- [`{q.field_id}`] **{q.label}** — {q.why}")
        lines += [
            "",
            "## Next",
            "",
            "1. Create `answers.yaml` next to this file with an entry for every `field_id` above.",
            "2. Add `approved_by:` and `approved_at:` (ISO-8601).",
            "3. Run the assisted fill. The browser opens, everything is filled, and it stops.",
            "   **You** review the form and click Submit yourself.",
        ]
        return "\n".join(lines)


def _value_hint(resolution: FormFieldResolution) -> str:
    if resolution.legal_sensitive or (resolution.policy and resolution.policy.value == "NEVER_GUESS"):
        return "[hidden]"
    value = (resolution.value or "").strip()
    if not value:
        return ""
    if resolution.canonical_key in {"email", "contact.email"}:
        name, _, domain = value.partition("@")
        return f"{name[:2]}…@{domain}" if domain else "…"
    if resolution.canonical_key in {"phone", "contact.phone"}:
        return f"…{value[-4:]}"
    return value if len(value) <= 40 else value[:37] + "…"


def build_review_packet(
    *,
    company: str,
    role: str,
    apply_url: str,
    ats: str,
    raw_fields: list[RawFormField],
    resolutions: list[FormFieldResolution],
    resume_fact_ids: list[str] | None = None,
) -> ReviewPacket:
    options_by_selector = {f.selector: list(f.options) for f in raw_fields}
    safe: list[SafeField] = []
    open_qs: list[OpenQuestion] = []
    blocked: list[OpenQuestion] = []
    optional_skipped = 0

    for i, r in enumerate(resolutions):
        if r.status == FormFieldStatus.FILLED:
            safe.append(SafeField(
                label=r.label,
                canonical_key=r.canonical_key,
                kind=r.kind.value,
                provenance=dict(r.source or {}),
                value_hint=_value_hint(r),
            ))
        elif r.status == FormFieldStatus.SKIPPED:
            optional_skipped += 1
        else:  # HUMAN_REQUIRED or BLOCKED
            q = OpenQuestion(
                field_id=f"q{i}",
                label=r.label,
                kind=r.kind.value,
                options=options_by_selector.get(r.selector, []),
                required=r.required,
                why=_REASON_HELP.get((r.reason or "").split(":")[0], r.reason or "Needs a human answer."),
            )
            (blocked if r.status == FormFieldStatus.BLOCKED else open_qs).append(q)

    return ReviewPacket(
        company=company,
        role=role,
        apply_url=apply_url,
        ats=ats,
        safe_prefill=safe,
        needs_your_answer=open_qs,
        optional_skipped=optional_skipped,
        blocked=blocked,
        resume_fact_ids=list(resume_fact_ids or []),
    )
