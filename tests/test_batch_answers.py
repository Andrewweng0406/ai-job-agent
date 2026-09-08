from datetime import datetime, timezone
import json

import pytest

from app.applications.batch_answers import (
    BatchAnswersError, load_batch_answers, rebind_fill_map, record_hash, validate_batch_answers,
)
from app.applications.live_field_scan import ScannedField
from app.applications.batch_prepare import BatchRecord


def _record():
    return {
        "company": "Acme", "role": "Analyst", "apply_url": "https://example.test/job",
        "ats": "ashby", "resume_pdf": "resume.pdf", "essay_text": None,
        "essay_reason": None, "optional_skipped": 0, "ready": False,
        "blockers": ["unmapped required: Work authorization"],
        "fields": [
            {"field_id": "q0", "label": "Name", "selector": "id=name", "kind": "text",
             "required": True, "source": "profile", "value": "Test Candidate", "display": "Test Candidate", "reason": None, "options": []},
            {"field_id": "q1", "label": "Work authorization", "selector": "name=auth", "kind": "radio_group",
             "required": True, "source": "unresolved", "value": None, "display": "", "reason": "candidate answer", "options": ["Current employer", "Any employer"]},
        ],
    }


def _approval(raw, **overrides):
    data = {
        "approved_by": "Test Candidate",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "record_hash": record_hash(raw),
        "apply_url": raw["apply_url"],
        "answers": {"q1": "Current employer"},
    }
    data.update(overrides)
    return data


def test_approved_batch_answers_are_hash_bound_and_fill_only_open_fields():
    raw = _record()
    approved = validate_batch_answers(raw, _approval(raw))
    assert approved.fill_map(__import__("app.applications.batch_prepare", fromlist=["BatchRecord"]).BatchRecord.from_dict(raw)) == {
        "name=auth": "Current employer"
    }


def test_batch_answers_reject_stale_hash_and_non_option():
    raw = _record()
    with pytest.raises(BatchAnswersError, match="hash mismatch"):
        validate_batch_answers(raw, _approval(raw, record_hash="0" * 64))
    with pytest.raises(BatchAnswersError, match="not an offered option"):
        validate_batch_answers(raw, _approval(raw, answers={"q1": "Guess"}))


def test_batch_answers_require_every_required_open_field():
    raw = _record()
    with pytest.raises(BatchAnswersError, match="missing required answers"):
        validate_batch_answers(raw, _approval(raw, answers={}))


def test_loading_tampered_approval_fails_closed(tmp_path):
    raw = _record()
    (tmp_path / "approval.json").write_text(json.dumps(_approval(raw)))
    raw["apply_url"] = "https://example.test/changed"
    with pytest.raises(BatchAnswersError, match="hash mismatch"):
        load_batch_answers(tmp_path, raw)


def test_rebind_uses_current_dynamic_selector_and_approved_value():
    raw = _record()
    record = BatchRecord.from_dict(raw)
    approved = validate_batch_answers(raw, _approval(raw))
    current = [
        ScannedField("Name", "text", "id=new-name", True),
        ScannedField("Work authorization", "radio_group", "name=random-new-id", True,
                     ["Current employer", "Any employer"]),
    ]

    assert rebind_fill_map(record, current, approved) == {
        "id=new-name": "Test Candidate",
        "name=random-new-id": "Current employer",
    }


def test_rebind_rejects_required_form_drift_and_ambiguous_fields():
    record = BatchRecord.from_dict(_record())
    with pytest.raises(BatchAnswersError, match="structure changed"):
        rebind_fill_map(record, [ScannedField("Name", "text", "id=name", True)])
    duplicated = [
        ScannedField("Name", "text", "id=name-1", True),
        ScannedField("Name", "text", "id=name-2", False),
        ScannedField("Work authorization", "radio_group", "name=auth", True),
    ]
    with pytest.raises(BatchAnswersError, match="uniquely rebound"):
        rebind_fill_map(record, duplicated)
