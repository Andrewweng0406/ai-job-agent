from scripts.batch_prepare import _slug, _wait_for_form


class _Locator:
    def __init__(self, visible: bool):
        self.visible = visible

    def wait_for(self, **_kwargs):
        if not self.visible:
            raise TimeoutError


class _ReactPage:
    def wait_for_load_state(self, *_args, **_kwargs):
        raise TimeoutError

    def wait_for_selector(self, selector, **_kwargs):
        if selector.startswith("input:not("):
            return _Locator(True)
        raise TimeoutError


def test_wait_for_form_accepts_ashby_react_form_without_form_element():
    assert _wait_for_form(_ReactPage())


def test_ashby_application_slugs_use_requisition_uuid_not_generic_suffix():
    first = _slug("Notion", "https://jobs.ashbyhq.com/notion/11111111-aaaa/application")
    second = _slug("Notion", "https://jobs.ashbyhq.com/notion/22222222-bbbb/application")

    assert first == "notion-11111111-aaaa"
    assert second == "notion-22222222-bbbb"
    assert first != second
