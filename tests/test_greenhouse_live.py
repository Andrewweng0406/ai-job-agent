from pathlib import Path

import pytest

from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.applications.greenhouse_live import GreenhouseLiveDryRunInput, GreenhouseLiveDryRunRunner
from app.models.enums import ApplicationStatus
from tests.test_greenhouse_dry_run import GREENHOUSE_FORM, _profile, _seed_ready_with_resume


def test_greenhouse_live_dry_run_navigates_and_stops_before_submit(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    page = _LivePage(GREENHOUSE_FORM)
    driver = _PlaywrightManager(page)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=False)
    runner = GreenhouseLiveDryRunRunner(adapter, playwright_factory=lambda: driver)
    screenshot_path = tmp_path / "greenhouse.png"

    result = runner.run(
        GreenhouseLiveDryRunInput(
            application_id=app_id,
            job=job,
            profile=_profile(),
            resume_id="resume-1",
            resume_path="data/resumes/resume-1.pdf",
            resume_hash="sha256:abc",
            resume_validation_status="VALIDATED",
            persona="DATA",
            screenshot_path=screenshot_path,
        )
    )

    assert result.status == ApplicationStatus.READY
    assert result.dry_run is not None
    assert result.dry_run.transcript.would_submit
    assert adapter.submit_call_count == 0
    assert page.goto_calls == [(job.apply_url, "domcontentloaded", 30_000)]
    assert page.screenshot_paths == [str(screenshot_path)]
    assert not page.clicks
    assert driver.browser.closed
    assert driver.context.closed


def test_greenhouse_live_runner_refuses_real_submission_enabled(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=True)
    runner = GreenhouseLiveDryRunRunner(adapter, playwright_factory=lambda: _PlaywrightManager(_LivePage("")))

    with pytest.raises(RuntimeError, match="refuses real_submission_enabled=True"):
        runner.run(
            GreenhouseLiveDryRunInput(
                application_id=app_id,
                job=job,
                profile=_profile(),
                resume_id="resume-1",
                resume_path="data/resumes/resume-1.pdf",
                resume_hash="sha256:abc",
                resume_validation_status="VALIDATED",
            )
        )


class _LivePage:
    def __init__(self, html: str) -> None:
        self.html = html
        self.goto_calls: list[tuple[str, str, int]] = []
        self.screenshot_paths: list[str] = []
        self.clicks: list[str] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> object:
        self.goto_calls.append((url, wait_until, timeout))
        return None

    def content(self) -> str:
        return self.html

    def screenshot(self, *, path: str) -> None:
        self.screenshot_paths.append(str(Path(path)))

    def click(self, selector: str) -> None:
        self.clicks.append(selector)


class _Context:
    def __init__(self, page: _LivePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> _LivePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _Browser:
    def __init__(self, context: _Context) -> None:
        self.context = context
        self.closed = False

    def new_context(self) -> _Context:
        return self.context

    def close(self) -> None:
        self.closed = True


class _Chromium:
    def __init__(self, browser: _Browser) -> None:
        self.browser = browser

    def launch(self, *, headless: bool) -> _Browser:
        assert headless is True
        return self.browser


class _Playwright:
    def __init__(self, chromium: _Chromium) -> None:
        self.chromium = chromium


class _PlaywrightManager:
    def __init__(self, page: _LivePage) -> None:
        self.context = _Context(page)
        self.browser = _Browser(self.context)
        self.playwright = _Playwright(_Chromium(self.browser))

    def __enter__(self) -> _Playwright:
        return self.playwright

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False
