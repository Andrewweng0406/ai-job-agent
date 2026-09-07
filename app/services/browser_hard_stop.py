from __future__ import annotations

from app.applications.browser_capture import BrowserCaptureResult
from app.applications.human_tasks import HumanTask
from app.models.enums import ApplicationStatus


def persist_browser_hard_stop(repository, application_id: str, job_id: int | None, capture: BrowserCaptureResult) -> bool:
    if not capture.human_required:
        return False
    first_reason = capture.blocking_reasons[0]
    for index, reason in enumerate(capture.blocking_reasons):
        task = HumanTask(
            application_id=application_id,
            job_id=job_id,
            category=reason,
            blocking_state=ApplicationStatus.READY.value,
            prompt=f"Browser hard stop detected: {reason}",
            context={"screenshot_path": capture.screenshot_path, "blocking_reasons": capture.blocking_reasons},
        )
        if index == 0:
            repository.mark_human_required(application_id, first_reason, task)
        else:
            repository.open_human_task(task)
    return True
