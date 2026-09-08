"""Resolve a captured application form to a review record for the batch flow.

Layering, in order, for each field the form marks:
  1. profile fact           (deterministic, from resolve_form_field FILLED)
  2. standard answer         (candidate's one-time answers)
  3. LLM essay              (only 'why this company' style; verified-facts-only)
  4. unresolved / must-queue (blocks auto-fill; the human handles it)

A record is `ready` only when every REQUIRED field resolved through 1-3 and no
free-text personal-narrative question is present. Nothing here submits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.applications.form_engine import FormFieldStatus, RawFormField, FormFieldResolution
from app.applications.standard_answers import (
    StandardAnswers, is_essay_question, is_must_queue_question,
)


@dataclass(frozen=True, slots=True)
class BatchField:
    field_id: str
    label: str
    selector: str
    kind: str
    required: bool
    source: str            # profile | standard_answer | essay | unresolved | must_queue
    value: str | None      # value to fill; None when unresolved
    display: str           # masked/short value for the review card
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRecord:
    company: str
    role: str
    apply_url: str
    ats: str
    resume_pdf: str
    fields: list[BatchField]
    essay_text: str | None
    essay_reason: str | None
    optional_skipped: int
    blockers: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.blockers

    def fill_map(self) -> dict[str, str]:
        """selector -> value for every field the agent will type."""
        return {f.selector: f.value for f in self.fields
                if f.value is not None and f.source in {"profile", "standard_answer", "essay"}}

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "fields"}
        d["fields"] = [asdict(f) for f in self.fields]
        d["ready"] = self.ready
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "BatchRecord":
        return cls(
            company=data["company"], role=data["role"], apply_url=data["apply_url"],
            ats=data["ats"], resume_pdf=data.get("resume_pdf", ""),
            fields=[BatchField(**f) for f in data.get("fields", [])],
            essay_text=data.get("essay_text"), essay_reason=data.get("essay_reason"),
            optional_skipped=int(data.get("optional_skipped", 0)),
            blockers=list(data.get("blockers", [])),
        )


def _display(resolution: FormFieldResolution, value: str) -> str:
    if resolution.legal_sensitive or (resolution.policy and resolution.policy.value == "NEVER_GUESS"):
        return "[hidden]"
    if not value:
        return ""
    return value if len(value) <= 60 else value[:57] + "…"


def build_batch_record(
    *,
    company: str,
    role: str,
    apply_url: str,
    ats: str,
    resume_pdf: str,
    raw_fields: list[RawFormField],
    resolutions: list[FormFieldResolution],
    standard_answers: StandardAnswers,
    jd_excerpt: str = "",
    essay_writer=None,
) -> BatchRecord:
    options_by_selector = {f.selector: list(f.options) for f in raw_fields}
    fields: list[BatchField] = []
    blockers: list[str] = []
    optional_skipped = 0
    essay_text: str | None = None
    essay_reason: str | None = None

    for i, r in enumerate(resolutions):
        fid = f"q{i}"
        if r.status == FormFieldStatus.FILLED:
            fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                     "profile", r.value, _display(r, r.value or "")))
            continue
        if r.status == FormFieldStatus.SKIPPED:
            optional_skipped += 1
            continue

        # HUMAN_REQUIRED / BLOCKED
        if is_must_queue_question(r.label):
            fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                     "must_queue", None, "", "personal narrative — you write this"))
            if r.required:
                blockers.append(f"needs you: {r.label[:60]}")
            continue

        label_low = r.label.lower()
        looks_essay = is_essay_question(r.label) or (
            label_low.startswith("why") and company.split()[0].lower() in label_low
        )
        if looks_essay:
            if essay_writer is None:
                fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                         "unresolved", None, "", "essay writer not configured"))
                if r.required:
                    blockers.append(f"essay unavailable: {r.label[:50]}")
                continue
            if essay_text is None and essay_reason is None:
                res = essay_writer.write(company=company, role=role,
                                         jd_excerpt=jd_excerpt, question=r.label)
                if res.ok:
                    essay_text = res.text
                else:
                    essay_reason = res.reason
            if essay_text is not None:
                fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                         "essay", essay_text, essay_text[:60] + "…"))
            else:
                fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                         "unresolved", None, "", f"essay rejected: {essay_reason}"))
                if r.required:
                    blockers.append(f"essay rejected ({essay_reason})")
            continue

        answer = standard_answers.resolve(r.label, options_by_selector.get(r.selector) or None)
        if answer:
            fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                     "standard_answer", answer, answer[:60]))
        else:
            fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                     "unresolved", None, "", "no profile fact or standard answer"))
            if r.required:
                blockers.append(f"unmapped required: {r.label[:60]}")

    return BatchRecord(company=company, role=role, apply_url=apply_url, ats=ats,
                       resume_pdf=resume_pdf, fields=fields, essay_text=essay_text,
                       essay_reason=essay_reason, optional_skipped=optional_skipped,
                       blockers=blockers)
