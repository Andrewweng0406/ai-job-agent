from scripts.batch_prepare import _follow_explicit_apply_form, _follow_greenhouse_embed, _no_form_reason


class _Links:
    def __init__(self, href):
        self.href = href

    @property
    def first(self):
        return self

    def count(self):
        return int(bool(self.href))

    def get_attribute(self, _name):
        return self.href


class _Page:
    def __init__(self, url, href=None, iframe=None):
        self.url = url
        self.href = href
        self.iframe = iframe
        self.visited = []

    def locator(self, selector):
        return _Links(self.iframe if selector.startswith("iframe") else self.href)

    def goto(self, target, **_kwargs):
        self.visited.append(target)
        self.url = target

    def wait_for_load_state(self, **_kwargs):
        return None

    def wait_for_selector(self, *_args, **_kwargs):
        return True


def test_follow_explicit_apply_form_requires_same_origin():
    page = _Page(
        "https://stripe.com/careers/listing/analyst/123",
        "/careers/apply/analyst/123",
    )
    assert _follow_explicit_apply_form(page, 1000)
    assert page.visited == ["https://stripe.com/careers/apply/analyst/123"]

    hostile = _Page("https://stripe.com/careers/listing/analyst/123", "https://evil.test/careers/apply/x")
    assert not _follow_explicit_apply_form(hostile, 1000)
    assert hostile.visited == []


def test_search_redirect_is_classified_as_closed_job():
    page = _Page("https://stripe.com/careers/search")
    assert _no_form_reason(page) == "JOB_NO_LONGER_AVAILABLE"
    page.url = "https://example.test/jobs/123"
    assert _no_form_reason(page) == "FORM_DID_NOT_LOAD"


def test_follow_greenhouse_embed_accepts_only_official_form_host():
    page = _Page(
        "https://stripe.com/careers/apply/analyst/123",
        iframe="https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=123",
    )
    assert _follow_greenhouse_embed(page, 1000)
    assert page.visited == [
        "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=123"
    ]

    hostile = _Page(
        "https://stripe.com/careers/apply/analyst/123",
        iframe="https://evil.test/embed/job_app?token=123",
    )
    assert not _follow_greenhouse_embed(hostile, 1000)
    assert hostile.visited == []
