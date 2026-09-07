from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter, GreenhouseDryRunResult
from app.models.job import Job
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


class GreenhouseLiveDryRunRunner:
    """Read-only Greenhouse page navigation that hands captured DOM to the dry-run adapter."""

    def __init__(self, adapter: GreenhouseDryRunAdapter, *, playwright_factory=None) -> None:
        self.adapter = adapter
        self.playwright_factory = playwright_factory

    def run(self, payload: GreenhouseLiveDryRunInput) -> GreenhouseDryRunResult:
        if self.adapter.real_submission_enabled:
            raise RuntimeError("Live dry-run runner refuses real_submission_enabled=True")
        manager = self._playwright_manager()
        with manager as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                try:
                    page = context.new_page()
                    page.goto(payload.job.apply_url, wait_until="domcontentloaded", timeout=payload.timeout_ms)
                    return self.adapter.dry_run(
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
                finally:
                    context.close()
            finally:
                browser.close()

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
