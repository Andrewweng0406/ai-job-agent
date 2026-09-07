from app.applications.browser_capture import BrowserFieldCapture


def test_browser_capture_extracts_fields_from_page_content(tmp_path):
    page = _FakePage(
        """
        <form>
          <label for="email">Email</label><input id="email" required />
          <label for="resume">Resume</label><input id="resume" type="file" required />
        </form>
        """
    )

    result = BrowserFieldCapture().capture(page, ats_type="greenhouse", screenshot_path=tmp_path / "shot.png")

    assert not result.human_required
    assert [field.label for field in result.fields] == ["Email", "Resume"]
    assert page.screenshot_paths == [str(tmp_path / "shot.png")]


def test_browser_capture_blocks_captcha_without_extracting_fields():
    page = _FakePage(
        """
        <main>
          <p>Verify you are human before continuing.</p>
          <form><label for="email">Email</label><input id="email" required /></form>
        </main>
        """
    )

    result = BrowserFieldCapture().capture(page, ats_type="lever")

    assert result.human_required
    assert result.blocking_reasons == ["BOT_WALL"]
    assert result.fields == []


def test_browser_capture_blocks_mfa_without_extracting_fields():
    page = _FakePage("<p>Enter the one-time password sent to your phone.</p>")

    result = BrowserFieldCapture().capture(page, ats_type="ashby")

    assert result.human_required
    assert result.blocking_reasons == ["MFA"]
    assert result.fields == []


class _FakePage:
    def __init__(self, html: str) -> None:
        self.html = html
        self.screenshot_paths: list[str] = []

    def content(self) -> str:
        return self.html

    def screenshot(self, *, path: str) -> None:
        self.screenshot_paths.append(path)
