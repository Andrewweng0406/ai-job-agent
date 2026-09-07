from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.applications.dry_run import DryRunTranscript
from app.applications.form_fields import FieldPolicy, classify_label, resolve_value
from app.applications.human_tasks import HumanTask
from app.models.application import requisition_key_for_job
from app.models.enums import ApplicationStatus, QuestionAnswerState
from app.models.job import Job
from app.resumes.profile import CandidateProfile


class InputKind(StrEnum):
    TEXT = "text"
    LONG_TEXT = "long_text"
    NUMERIC = "numeric"
    DATE = "date"
    BOOL = "bool"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    FILE = "file"


class FormFieldStatus(StrEnum):
    FILLED = "FILLED"
    SKIPPED = "SKIPPED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class RawFormField:
    label: str
    kind: InputKind
    selector: str
    required: bool = False
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FormFieldResolution:
    label: str
    selector: str
    kind: InputKind
    required: bool
    status: FormFieldStatus
    canonical_key: str | None = None
    value: str | None = None
    policy: FieldPolicy | None = None
    source: dict[str, str] = field(default_factory=dict)
    confidence: str | None = None
    reason: str | None = None
    legal_sensitive: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "selector": self.selector,
            "kind": self.kind.value,
            "required_by_form": self.required,
            "status": self.status.value,
            "canonical_key": self.canonical_key,
            "value": self.value,
            "policy": self.policy.value if self.policy else None,
            "source": self.source,
            "confidence": self.confidence,
            "reason": self.reason,
            "legal_sensitive": self.legal_sensitive,
        }


@dataclass(frozen=True, slots=True)
class FormDryRunResult:
    transcript: DryRunTranscript
    resolutions: list[FormFieldResolution]
    status: ApplicationStatus


class FormDryRunEngine:
    def __init__(self, repository, real_submission_enabled: bool = False) -> None:
        self.repository = repository
        self.real_submission_enabled = real_submission_enabled

    def build_transcript(
        self,
        *,
        application_id: str,
        job: Job,
        profile: CandidateProfile,
        resume_id: str,
        resume_path: str,
        resume_hash: str,
        fields: list[RawFormField],
        resume_validation_status: str = "VALIDATED",
        persona: str | None = None,
    ) -> FormDryRunResult:
        resume_validated = resume_validation_status.upper() in {"VALIDATED", "PASS", "PASSED"}
        resolutions = [resolve_form_field(field, profile, resume_path, resume_validated=resume_validated) for field in fields]
        unresolved = [
            {
                "kind": "field",
                "ref": resolution.canonical_key or resolution.label,
                "reason": resolution.reason or resolution.status.value,
            }
            for resolution in resolutions
            if resolution.status in {FormFieldStatus.HUMAN_REQUIRED, FormFieldStatus.BLOCKED}
        ]
        blocking_reasons = sorted({str(item["reason"]).split(":")[0] for item in unresolved})
        would_submit = not unresolved and all(
            resolution.status in {FormFieldStatus.FILLED, FormFieldStatus.SKIPPED}
            for resolution in resolutions
        )
        payload = {
            "real_submission_enabled": self.real_submission_enabled,
            "job": {
                "company": job.company_name,
                "role": job.title,
                "ats": job.ats_type,
                "job_id": job.id,
                "requisition_key": requisition_key_for_job(job),
                "apply_url": job.apply_url,
                "job_content_hash": job.description_hash,
            },
            "persona": persona,
            "resume": {
                "resume_id": resume_id,
                "file": resume_path,
                "file_hash": resume_hash,
                "truth_validation": resume_validation_status,
            },
            "fields": [resolution.to_payload() for resolution in resolutions],
            "unresolved": unresolved,
            "would_submit": would_submit,
            "blocking_reasons": blocking_reasons,
        }
        transcript = DryRunTranscript(
            application_id=application_id,
            job_id=int(job.id or 0),
            payload=payload,
            would_submit=would_submit,
            blocking_reasons=blocking_reasons,
            generator_version="form-engine@1",
        )
        self.repository.insert_dry_run_transcript(transcript)
        if unresolved:
            first_reason = blocking_reasons[0] if blocking_reasons else "FORM_MAPPING"
            self.repository.mark_human_required(
                application_id,
                first_reason,
                HumanTask(
                    application_id=application_id,
                    job_id=job.id,
                    category=first_reason,
                    blocking_state=ApplicationStatus.READY.value,
                    prompt="Application dry-run has unresolved required fields.",
                    context={"unresolved": unresolved, "transcript_id": transcript.transcript_id},
                ),
            )
            for reason in blocking_reasons[1:]:
                self.repository.open_human_task(
                    HumanTask(
                        application_id=application_id,
                        job_id=job.id,
                        category=reason,
                        blocking_state=ApplicationStatus.HUMAN_REQUIRED.value,
                        prompt="Application dry-run has unresolved required fields.",
                        context={"unresolved": unresolved, "transcript_id": transcript.transcript_id},
                    )
                )
            return FormDryRunResult(transcript, resolutions, ApplicationStatus.HUMAN_REQUIRED)
        return FormDryRunResult(transcript, resolutions, ApplicationStatus.READY)


def resolve_form_field(field: RawFormField, profile: CandidateProfile, resume_path: str, resume_validated: bool = True) -> FormFieldResolution:
    spec = classify_label(field.label, field.options)
    if spec is None:
        status = FormFieldStatus.HUMAN_REQUIRED if field.required else FormFieldStatus.SKIPPED
        return FormFieldResolution(
            label=field.label,
            selector=field.selector,
            kind=field.kind,
            required=field.required,
            status=status,
            reason="FORM_MAPPING" if field.required else "OPTIONAL_SKIP",
        )
    if spec.canonical_key == "application.resume":
        if not resume_validated:
            return FormFieldResolution(
                label=field.label,
                selector=field.selector,
                kind=field.kind,
                required=field.required,
                status=FormFieldStatus.BLOCKED,
                canonical_key=spec.canonical_key,
                policy=spec.policy,
                reason="TRUTH_VALIDATION_FAILED",
            )
        return FormFieldResolution(
            label=field.label,
            selector=field.selector,
            kind=field.kind,
            required=field.required,
            status=FormFieldStatus.FILLED,
            canonical_key=spec.canonical_key,
            value=resume_path,
            policy=spec.policy,
            source={"resume_artifact": "validated"},
            confidence="PROFILE",
        )

    resolved = resolve_value(spec, profile)
    legal_sensitive = spec.policy == FieldPolicy.NEVER_GUESS
    if resolved.state in {QuestionAnswerState.AUTO_SAFE, QuestionAnswerState.AUTO_FROM_PROFILE}:
        value = resolved.value
        if field.kind in {InputKind.SELECT, InputKind.MULTI_SELECT} and field.options:
            value = _map_select_value(value or "", field.options, spec.canonical_key)
            if value is None:
                return FormFieldResolution(
                    label=field.label,
                    selector=field.selector,
                    kind=field.kind,
                    required=field.required,
                    status=FormFieldStatus.HUMAN_REQUIRED,
                    canonical_key=spec.canonical_key,
                    policy=spec.policy,
                    reason="FORM_MAPPING",
                    legal_sensitive=legal_sensitive,
                )
        return FormFieldResolution(
            label=field.label,
            selector=field.selector,
            kind=field.kind,
            required=field.required,
            status=FormFieldStatus.FILLED,
            canonical_key=spec.canonical_key,
            value=value,
            policy=spec.policy,
            source=_source_for_spec(spec),
            confidence=resolved.state.value,
            legal_sensitive=legal_sensitive,
        )
    if resolved.reason == "OPTIONAL_SKIP" and not field.required:
        return FormFieldResolution(
            label=field.label,
            selector=field.selector,
            kind=field.kind,
            required=field.required,
            status=FormFieldStatus.SKIPPED,
            canonical_key=spec.canonical_key,
            policy=spec.policy,
            reason="OPTIONAL_SKIP",
            legal_sensitive=legal_sensitive,
        )
    return FormFieldResolution(
        label=field.label,
        selector=field.selector,
        kind=field.kind,
        required=field.required,
        status=FormFieldStatus.BLOCKED if resolved.reason and resolved.reason.startswith("PROFILE_INCOMPLETE") else FormFieldStatus.HUMAN_REQUIRED,
        canonical_key=spec.canonical_key,
        policy=spec.policy,
        reason=resolved.reason or "HUMAN_REQUIRED",
        legal_sensitive=legal_sensitive,
    )


def _source_for_spec(spec) -> dict[str, str]:
    if spec.fact_id:
        return {"fact_id": spec.fact_id}
    if spec.answer_key:
        return {"answer_key": spec.answer_key}
    if spec.constant:
        return {"constant": spec.constant}
    return {}


def _map_select_value(value: str, options: list[str], canonical_key: str) -> str | None:
    normalized_value = _normalize_option(value)
    for option in options:
        if _normalize_option(option) == normalized_value:
            return option
    if canonical_key == "requires_sponsorship":
        wants_yes = normalized_value in {"yes", "true", "1"}
        wants_no = normalized_value in {"no", "false", "0"}
        for option in options:
            normalized = _normalize_option(option)
            if wants_yes and "require" in normalized and "sponsorship" in normalized and "not require" not in normalized and "do not" not in normalized:
                return option
            if wants_no and (("do not" in normalized or "not require" in normalized) and "sponsorship" in normalized):
                return option
    if canonical_key == "work_authorized_us":
        wants_yes = normalized_value in {"yes", "true", "1"}
        wants_no = normalized_value in {"no", "false", "0"}
        for option in options:
            normalized = _normalize_option(option)
            if wants_yes and normalized in {"yes", "yes i am", "authorized", "i am authorized"}:
                return option
            if wants_no and normalized in {"no", "no i am not", "not authorized"}:
                return option
    return None


def _normalize_option(value: str) -> str:
    return " ".join(value.lower().replace(".", "").split())
