from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

from app.applications.batch_prepare import BATCH_RECORD_SCHEMA_VERSION, BatchRecord
from app.applications.live_field_scan import ScannedField


class BatchAnswersError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedBatchAnswers:
    approved_by: str
    approved_at: str
    record_hash: str
    answers: dict[str, str]

    def fill_map(self, record: BatchRecord) -> dict[str, str]:
        by_id = {field.field_id: field for field in record.fields}
        return {by_id[field_id].selector: value for field_id, value in self.answers.items()}


def record_hash(raw: dict) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def validate_batch_answers(raw: dict, approval: dict) -> ApprovedBatchAnswers:
    if raw.get("blocked"):
        raise BatchAnswersError("record is blocked")
    record = BatchRecord.from_dict(raw)
    if record.schema_version != BATCH_RECORD_SCHEMA_VERSION:
        raise BatchAnswersError("stale review record; prepare it again")
    approved_by = str(approval.get("approved_by") or "").strip()
    approved_at = str(approval.get("approved_at") or "").strip()
    if not approved_by:
        raise BatchAnswersError("missing approved_by")
    try:
        datetime.fromisoformat(approved_at)
    except ValueError as exc:
        raise BatchAnswersError("approved_at is not ISO-8601") from exc
    expected_hash = record_hash(raw)
    if approval.get("record_hash") != expected_hash:
        raise BatchAnswersError("record hash mismatch; review the refreshed form")
    if approval.get("apply_url") != record.apply_url:
        raise BatchAnswersError("application URL mismatch")

    supplied = approval.get("answers") or {}
    if not isinstance(supplied, dict):
        raise BatchAnswersError("answers must be a mapping")
    answers = {str(key): str(value).strip() for key, value in supplied.items() if str(value).strip()}
    open_fields = {field.field_id: field for field in record.fields
                   if field.source in {"unresolved", "must_queue"}}
    unknown = sorted(set(answers) - set(open_fields))
    if unknown:
        raise BatchAnswersError(f"answers contain unknown fields: {unknown}")
    for field_id, value in answers.items():
        options = open_fields[field_id].options
        if options and value not in options:
            raise BatchAnswersError(f"answer for {field_id} is not an offered option")
    missing = [field.label for field in open_fields.values()
               if field.required and not answers.get(field.field_id)]
    if missing:
        raise BatchAnswersError("missing required answers: " + "; ".join(missing))
    if any(blocker.startswith("could not fill") for blocker in record.blockers):
        raise BatchAnswersError("preparation contains browser fill failures")
    return ApprovedBatchAnswers(approved_by, approved_at, expected_hash, answers)


def load_batch_answers(record_dir: Path, raw: dict) -> ApprovedBatchAnswers:
    path = record_dir / "approval.json"
    if not path.is_file():
        raise BatchAnswersError("human answers are not approved")
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BatchAnswersError("approval artifact is invalid") from exc
    return validate_batch_answers(raw, approval)


def rebind_fill_map(
    record: BatchRecord,
    current_fields: list[ScannedField],
    approved: ApprovedBatchAnswers | None = None,
) -> dict[str, str]:
    """Bind reviewed values to selectors from the current render, rejecting drift."""
    expected_required = Counter(_field_key(field.label, field.kind) for field in record.fields if field.required)
    current_required = Counter(_field_key(field.label, field.kind) for field in current_fields if field.required)
    if expected_required != current_required:
        raise BatchAnswersError("required form structure changed; prepare a fresh review")

    current_by_key: dict[tuple[str, str], list[ScannedField]] = defaultdict(list)
    for field in current_fields:
        current_by_key[_field_key(field.label, field.kind)].append(field)

    values = {field.field_id: field.value for field in record.fields
              if field.value is not None and field.source in {"profile", "standard_answer", "essay"}}
    if approved is not None:
        values.update(approved.answers)
    record_by_id = {field.field_id: field for field in record.fields}
    rebound: dict[str, str] = {}
    for field_id, value in values.items():
        field = record_by_id[field_id]
        candidates = current_by_key.get(_field_key(field.label, field.kind), [])
        if len(candidates) != 1:
            raise BatchAnswersError(f"field cannot be uniquely rebound: {field.label}")
        selector = candidates[0].selector
        if selector in rebound and rebound[selector] != value:
            raise BatchAnswersError(f"selector collision after rebind: {field.label}")
        rebound[selector] = value
    return rebound


def _field_key(label: str, kind: str) -> tuple[str, str]:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", label.lower()).split())
    return normalized, kind
