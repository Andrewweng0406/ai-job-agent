from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
import hashlib
import json

from app.models.enums import Persona
from app.models.job import Job, utc_now
from app.resumes.pdf import render_simple_pdf
from app.resumes.profile import CandidateProfile, profile_completeness_gate
from app.resumes.truth_validation import check_required_fields, validate_claims_against_profile


@dataclass(frozen=True, slots=True)
class ResumeArtifact:
    resume_id: str
    job_id: int
    persona: Persona
    base_version: str
    generated_at: str
    changes: dict[str, object]
    validation_status: str
    file_path: str
    file_hash: str


@dataclass(frozen=True, slots=True)
class ResumeGenerationResult:
    artifact: ResumeArtifact | None
    human_required_reason: str | None = None
    missing_fact_ids: list[str] = field(default_factory=list)


class DeterministicResumeGenerator:
    def __init__(self, output_dir: str | Path = "data/resumes") -> None:
        self.output_dir = Path(output_dir)

    def generate(self, profile: CandidateProfile, job: Job, persona: Persona, selected_fact_ids: list[str]) -> ResumeGenerationResult:
        completeness = profile_completeness_gate(profile)
        if not completeness.complete:
            return ResumeGenerationResult(
                artifact=None,
                human_required_reason="PROFILE_INCOMPLETE",
                missing_fact_ids=completeness.missing_fact_ids,
            )

        fact_text = profile.supported_fact_text(selected_fact_ids)
        sections = self._render_sections(profile, job, persona, fact_text)
        required = check_required_fields(sections, [fact_id for fact_id, fact in profile.facts.items() if fact.required and fact.type == "education"])
        if not required.valid:
            return ResumeGenerationResult(
                artifact=None,
                human_required_reason="REQUIRED_RESUME_FACT_MISSING",
                missing_fact_ids=required.missing,
            )

        bullets = [line[2:] for line in sections["facts"].splitlines() if line.startswith("- ")]
        truth = validate_claims_against_profile(bullets, fact_text)
        if not truth.valid:
            return ResumeGenerationResult(
                artifact=None,
                human_required_reason="TRUTH_VALIDATION_FAILED",
                missing_fact_ids=truth.unsupported_claims,
            )

        content = self._render_text(sections)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        resume_id = _resume_id(job, persona, profile.schema_version, selected_fact_ids)
        base_name = _artifact_base_name(job, resume_id)
        json_path = self.output_dir / f"{base_name}.json"
        pdf_path = self.output_dir / f"{base_name}.pdf"
        json_path.write_text(json.dumps({"sections": sections}, indent=2, sort_keys=True), encoding="utf-8")
        pdf_bytes = render_simple_pdf(content.splitlines())
        pdf_path.write_bytes(pdf_bytes)
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        artifact = ResumeArtifact(
            resume_id=resume_id,
            job_id=job.id or 0,
            persona=persona,
            base_version=f"profile-v{profile.schema_version}",
            generated_at=utc_now().astimezone(timezone.utc).isoformat(),
            changes={"mode": "deterministic", "selected_fact_ids": selected_fact_ids, "structured_json_path": str(json_path)},
            validation_status="VALIDATED",
            file_path=str(pdf_path),
            file_hash=file_hash,
        )
        return ResumeGenerationResult(artifact=artifact)

    def _render_sections(self, profile: CandidateProfile, job: Job, persona: Persona, fact_text: list[str]) -> dict[str, str]:
        name = str(profile.facts.get("name.full").value)
        education = "\n".join(str(fact.value) for fact in profile.facts.values() if fact.type == "education")
        facts = "\n".join(f"- {fact}" for fact in fact_text)
        return {
            "header": name,
            "target": f"Target Role: {job.title} | Persona: {persona.value}",
            "education": education,
            "facts": facts,
        }

    def _render_text(self, sections: dict[str, str]) -> str:
        return "\n\n".join(
            [
                sections["header"],
                sections["target"],
                "Education\n" + sections["education"],
                "Relevant Facts\n" + sections["facts"],
            ]
        )


def artifact_to_db_tuple(artifact: ResumeArtifact) -> tuple[object, ...]:
    return (
        artifact.resume_id,
        artifact.job_id,
        artifact.persona.value,
        artifact.base_version,
        artifact.generated_at,
        json.dumps(artifact.changes, sort_keys=True),
        artifact.validation_status,
        artifact.file_path,
        artifact.file_hash,
    )


def _artifact_base_name(job: Job, resume_id: str) -> str:
    safe_company = _safe_name(job.company_name)
    safe_role = _safe_name(job.title)
    safe_job = _safe_name(job.external_job_id)
    return f"{safe_company}_{safe_role}_{safe_job}_{resume_id}_resume"


def _resume_id(job: Job, persona: Persona, schema_version: int, selected_fact_ids: list[str]) -> str:
    signature = "|".join(
        [
            job.company_id,
            job.external_job_id,
            persona.value,
            str(schema_version),
            ",".join(sorted(selected_fact_ids)),
        ]
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def _safe_name(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    return "_".join(part for part in cleaned.split("_") if part)[:80] or "artifact"
