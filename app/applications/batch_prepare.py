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
import re

from app.applications.form_engine import FormFieldStatus, RawFormField, FormFieldResolution
from app.applications.standard_answers import (
    StandardAnswers, is_essay_question, is_experience_question, is_must_queue_question,
)

BATCH_RECORD_SCHEMA_VERSION = 2


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
    options: list[str] = field(default_factory=list)


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
    schema_version: int = BATCH_RECORD_SCHEMA_VERSION

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
            schema_version=int(data.get("schema_version", 1)),
        )


def _display(resolution: FormFieldResolution, value: str) -> str:
    if resolution.legal_sensitive or (resolution.policy and resolution.policy.value == "NEVER_GUESS"):
        return "[hidden]"
    if not value:
        return ""
    return value if len(value) <= 60 else value[:57] + "…"


_PROFILE_LABEL_MAP = [
    (("full name", "your name", "legal name", "first and last"), "name.full"),
    (("first name",), "name.first"),
    (("last name", "surname", "family name"), "name.last"),
    (("email",), "contact.email"),
    (("phone", "mobile", "telephone"), "contact.phone"),
    (("linkedin",), "links.linkedin"),
    (("github", "git hub"), "links.github"),
    (("school", "university", "college", "institution"), "edu.primary.school"),
    (("portfolio", "website", "personal site"), "links.portfolio"),
]


def _profile_value(profile: CandidateProfile, label: str) -> tuple[str, str] | None:
    low = " ".join(label.lower().replace("*", " ").split())
    if "preferred" in low or "nickname" in low:
        return None
    if "i confirm" in low and "graduation date" in low:
        fact = profile.facts.get("edu.primary.grad_date")
        value = "" if fact is None or fact.is_missing else str(fact.value)
        match = re.search(
            r"\b(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+(20\d{2})\b",
            value,
            re.I,
        )
        if match:
            month = match.group(1).lower()
            year = match.group(2)
            spring = month in {"january", "february", "march", "april", "may", "june"}
            season = "spring" if spring else "fall"
            if f"{season} {year}" in low:
                return ("Yes", "edu.primary.grad_date")
    if low in {"name", "candidate name"}:
        fact = profile.facts.get("name.full")
        return (str(fact.value), "name.full") if fact and not fact.is_missing else None
    if low in {"start date month", "start date year"}:
        fact = profile.facts.get("edu.primary.start_date")
        value = "" if fact is None or fact.is_missing else str(fact.value)
        match = re.fullmatch(
            r"(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+(20\d{2})",
            value.strip(), re.I,
        )
        if match:
            return (match.group(1).title() if low.endswith("month") else match.group(2),
                    "edu.primary.start_date")
    for needles, fid in _PROFILE_LABEL_MAP:
        if not _profile_fact_matches_label(fid, low, needles):
            continue
        if any(n in low for n in needles):
            if fid == "name.first":
                f = profile.facts.get("name.full")
                return (str(f.value).split()[0], "name.full") if f and not f.is_missing else None
            if fid == "name.last":
                f = profile.facts.get("name.full")
                parts = str(f.value).split() if f and not f.is_missing else []
                return (" ".join(parts[1:]), "name.full") if len(parts) > 1 else None
            f = profile.facts.get(fid)
            if f and not f.is_missing:
                return (str(f.value), fid)
    return None


def _profile_fact_matches_label(fact_id: str, label: str, needles: tuple[str, ...]) -> bool:
    """Defense in depth against a polluted label routing identity/contact facts."""
    if fact_id == "name.full":
        return label in {"full name", "your name", "legal name", "first and last name"}
    if fact_id == "name.first":
        return label in {"first name", "legal first name", "given name"}
    if fact_id == "name.last":
        return label in {"last name", "legal last name", "surname", "family name"}
    if fact_id == "contact.email":
        return label in {"email", "email address", "personal email", "preferred email"}
    if fact_id == "contact.phone":
        return bool(re.fullmatch(r"(phone|phone number|mobile|mobile phone|telephone)( number)?", label))
    if fact_id == "links.linkedin":
        return "linkedin" in label and len(label) <= 80
    if fact_id == "links.github":
        return ("github" in label or "git hub" in label) and len(label) <= 80
    if fact_id == "edu.primary.school":
        return any(needle in label for needle in needles) and len(label) <= 120
    if fact_id == "links.portfolio":
        return label in {"portfolio", "portfolio url", "website", "personal site", "personal website"}
    return False


def resolve_scanned(
    *,
    company: str,
    role: str,
    apply_url: str,
    ats: str,
    resume_pdf: str,
    scanned: list,                       # list[ScannedField]
    profile: CandidateProfile,
    standard_answers: StandardAnswers,
    jd_excerpt: str = "",
    essay_writer=None,
) -> BatchRecord:
    fields: list[BatchField] = []
    blockers: list[str] = []
    essay_text: str | None = None
    essay_reason: str | None = None

    for i, sf in enumerate(scanned):
        fid = f"q{i}"
        label, kind, sel, required = sf.label, sf.kind, sf.selector, sf.required
        opts = list(sf.options)

        # Greenhouse's optional phone-country widget collapses a selected
        # country to its dialing code (for example +1), which is not unique
        # enough to verify. Leave it for the applicant instead of claiming a
        # successful fill. Required country fields still go through resolution.
        if label.strip().lower() == "country" and not required:
            fields.append(BatchField(fid, label, sel, kind, required, "unresolved", None, "",
                                     "optional phone country cannot be uniquely verified", opts))
            continue

        if kind == "file":
            is_resume = any(word in label.lower() for word in ("resume", "résumé", "cv"))
            value = resume_pdf if is_resume else None
            source = "profile" if value else "unresolved"
            fields.append(BatchField(fid, label, sel, kind, required, source,
                                     value, "résumé" if value else "",
                                     None if value else "non-resume upload left for human"))
            if required and not value:
                blockers.append(f"required file needs you: {label[:60]}")
            continue

        pv = _profile_value(profile, label) if kind in {
            "text", "long_text", "numeric", "combobox", "select"
        } else None
        if pv:
            fields.append(BatchField(fid, label, sel, kind, required, "profile", pv[0],
                                     _hint(label, pv[0]), None))
            continue

        low = label.lower()
        looks_essay = kind == "long_text" and (
            is_essay_question(label) or (low.startswith("why") and company.split()[0].lower() in low)
        )
        if looks_essay and essay_writer is not None:
            if essay_text is None and essay_reason is None:
                r = essay_writer.write(company=company, role=role, jd_excerpt=jd_excerpt, question=label)
                essay_text, essay_reason = (r.text, None) if r.ok else (None, r.reason)
            if essay_text is not None:
                fields.append(BatchField(fid, label, sel, kind, required, "essay", essay_text,
                                         essay_text[:60] + "…", "AI draft — review before submitting"))
            else:
                fields.append(BatchField(fid, label, sel, kind, required, "unresolved", None, "",
                                         f"essay rejected: {essay_reason}"))
                if required:
                    blockers.append(f"essay rejected ({essay_reason})")
            continue

        if kind == "long_text" and is_experience_question(label) and essay_writer is not None:
            d = essay_writer.answer_experience(question=label, role=role)
            if d.ok:
                fields.append(BatchField(fid, label, sel, kind, required, "essay", d.text,
                                         d.text[:60] + "…", "AI draft — review before submitting"))
            else:
                fields.append(BatchField(fid, label, sel, kind, required, "unresolved", None, "",
                                         f"draft rejected: {d.reason}"))
                if required:
                    blockers.append(f"you write: {label[:55]}")
            continue

        exact_answer = standard_answers.resolve_exact(company, label, opts or None)
        if exact_answer:
            fields.append(BatchField(fid, label, sel, kind, required, "standard_answer",
                                     exact_answer, exact_answer[:60],
                                     "candidate-approved exact company question", opts))
            continue

        if is_must_queue_question(label) or is_experience_question(label):
            fields.append(BatchField(fid, label, sel, kind, required, "must_queue", None, "",
                                     "personal narrative / disclosure — you handle this", opts))
            if required:
                blockers.append(f"needs you: {label[:60]}")
            continue

        # ATS education rows often call attendance controls "Start date". That is
        # not the candidate's job-availability date and must never use that answer.
        education_date = bool(re.search(r"\b(start|end) date (month|year)\b", low))
        answer = None if education_date else standard_answers.resolve(label, opts or None)
        if answer:
            fields.append(BatchField(fid, label, sel, kind, required, "standard_answer", answer,
                                     answer[:60], None))
        else:
            fields.append(BatchField(fid, label, sel, kind, required, "unresolved", None, "",
                                     "no profile fact or standard answer", opts))
            if required:
                blockers.append(f"unmapped required: {label[:60]}")

    return BatchRecord(company=company, role=role, apply_url=apply_url, ats=ats,
                       resume_pdf=resume_pdf, fields=fields, essay_text=essay_text,
                       essay_reason=essay_reason, optional_skipped=0, blockers=blockers)


def _hint(label: str, value: str) -> str:
    low = label.lower()
    if "email" in low:
        n, _, d = value.partition("@")
        return f"{n[:2]}…@{d}" if d else "…"
    if "phone" in low:
        return f"…{value[-4:]}"
    return value if len(value) <= 44 else value[:41] + "…"


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
        if is_experience_question(r.label) and essay_writer is not None:
            draft = essay_writer.answer_experience(question=r.label, role=role)
            if draft.ok:
                fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                         "essay", draft.text, draft.text[:60] + "…",
                                         "AI draft — review before submitting"))
                continue
            fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                     "unresolved", None, "", f"draft rejected: {draft.reason}"))
            if r.required:
                blockers.append(f"you write: {r.label[:55]}")
            continue

        exact_answer = standard_answers.resolve_exact(
            company, r.label, options_by_selector.get(r.selector) or None
        )
        if exact_answer:
            fields.append(BatchField(fid, r.label, r.selector, r.kind.value, r.required,
                                     "standard_answer", exact_answer, exact_answer[:60],
                                     "candidate-approved exact company question"))
            continue

        if is_must_queue_question(r.label) or is_experience_question(r.label):
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
