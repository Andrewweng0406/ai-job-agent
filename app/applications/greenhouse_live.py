from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.applications.browser_autofill import BrowserAutofillResult, DryRunBrowserAutofill
from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter, GreenhouseDryRunResult
from app.applications.preview import ApprovedAutofillPreviewBuilder
from app.models.job import Job
from app.models.enums import ApplicationStatus
from app.resumes.profile import CandidateProfile


class LivePage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def content(self) -> str: ...

    def screenshot(self, *, path: str) -> None: ...


class LiveBrowserContext(Protocol):
    def new_page(self) -> LivePage: ...

    def close(self) -> None: ...


class LiveBrowser(Protocol):
    def new_context(self) -> LiveBrowserContext: ...

    def close(self) -> None: ...


class SyncPlaywrightLike(Protocol):
    @property
    def chromium(self) -> object: ...


@dataclass(frozen=True, slots=True)
class GreenhouseLiveDryRunInput:
    application_id: str
    job: Job
    profile: CandidateProfile
    resume_id: str
    resume_path: str
    resume_hash: str
    resume_validation_status: str
    persona: str | None = None
    screenshot_path: str | Path | None = None
    timeout_ms: int = 30_000
    autofill: bool = True
    human_invoked: bool = False
    worker_id: str | None = None
    lease_epoch: int | None = None
    approved_transcript_id: str | None = None


@dataclass(frozen=True, slots=True)
class GreenhouseLiveDryRunResult:
    adapter_result: GreenhouseDryRunResult
    autofill: BrowserAutofillResult

    @property
    def status(self):
        return self.adapter_result.status

    @property
    def dry_run(self):
        return self.adapter_result.dry_run

    @property
    def reason(self):
        return self.adapter_result.reason


class GreenhouseLiveDryRunRunner:
    """Read-only Greenhouse page navigation that hands captured DOM to the dry-run adapter."""

    def __init__(self, adapter: GreenhouseDryRunAdapter, *, playwright_factory=None) -> None:
        self.adapter = adapter
        self.playwright_factory = playwright_factory
        self.autofill = DryRunBrowserAutofill()

    def run(self, payload: GreenhouseLiveDryRunInput) -> GreenhouseLiveDryRunResult:
        if self.adapter.real_submission_enabled:
            raise RuntimeError("Live dry-run runner refuses real_submission_enabled=True")
        self._assert_lease(payload)
        if payload.autofill and not payload.approved_transcript_id:
            raise RuntimeError("Live autofill requires approved_transcript_id")
        if payload.autofill and payload.approved_transcript_id:
            ApprovedAutofillPreviewBuilder(self.adapter.repository).build(payload.approved_transcript_id)
        manager = self._playwright_manager()
        with manager as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                try:
                    page = context.new_page()
                    self._assert_lease(payload)
                    page.goto(payload.job.apply_url, wait_until="domcontentloaded", timeout=payload.timeout_ms)
                    self._assert_lease(payload)
                    adapter_result = self.adapter.dry_run(
                        page=page,
                        application_id=payload.application_id,
                        job=payload.job,
                        profile=payload.profile,
                        resume_id=payload.resume_id,
                        resume_path=payload.resume_path,
                        resume_hash=payload.resume_hash,
                        resume_validation_status=payload.resume_validation_status,
                        persona=payload.persona,
                        screenshot_path=payload.screenshot_path,
                    )
                    autofill = BrowserAutofillResult([], 0)
                    if payload.autofill and not payload.human_invoked:
                        raise RuntimeError("Live autofill requires explicit human_invoked=True")
                    if payload.autofill and adapter_result.dry_run is not None:
                        self._assert_lease(payload)
                        autofill = self.autofill.apply(
                            page,
                            adapter_result.dry_run.resolutions,
                            expected_resume_hash=payload.resume_hash,
                        )
                        self._assert_lease(payload)
                        post_fill = self.adapter.capture.capture(
                            page, ats_type="greenhouse", screenshot_path=payload.screenshot_path
                        )
                        if post_fill.human_required:
                            from app.services.browser_hard_stop import persist_browser_hard_stop

                            persist_browser_hard_stop(
                                self.adapter.repository, payload.application_id, payload.job.id, post_fill
                            )
                            return GreenhouseLiveDryRunResult(
                                GreenhouseDryRunResult(ApplicationStatus.HUMAN_REQUIRED, reason="BROWSER_HARD_STOP"),
                                autofill,
                            )
                    return GreenhouseLiveDryRunResult(adapter_result, autofill)
                finally:
                    context.close()
            finally:
                browser.close()

    def _assert_lease(self, payload: GreenhouseLiveDryRunInput) -> None:
        if payload.worker_id is None or payload.lease_epoch is None:
            return
        if not self.adapter.repository.lease_still_mine(
            payload.application_id, payload.worker_id, payload.lease_epoch
        ):
            raise RuntimeError("LEASE_LOST")

    def _playwright_manager(self):
        if self.playwright_factory is not None:
            return self.playwright_factory()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install the optional browser dependency before live dry-run navigation."
            ) from exc
        return sync_playwright()
