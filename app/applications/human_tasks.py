from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class HumanTask:
    category: str
    blocking_state: str
    prompt: str
    application_id: str | None = None
    job_id: int | None = None
    task_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "OPEN"
    options: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    resume_token: str | None = None
    resolution: dict[str, Any] | None = None
    resolved_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None

