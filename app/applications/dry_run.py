from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import hashlib
import json


@dataclass(frozen=True, slots=True)
class DryRunTranscript:
    application_id: str
    job_id: int
    payload: dict[str, Any]
    would_submit: bool
    blocking_reasons: list[str] = field(default_factory=list)
    transcript_id: str = field(default_factory=lambda: f"dry_{uuid4()}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    generator_version: str = "dry-run@1"

    def payload_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True)

    def payload_hash(self) -> str:
        return hashlib.sha256(self.payload_json().encode("utf-8")).hexdigest()

