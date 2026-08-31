"""Isolated session ownership tests using fakes instead of a browser."""

import pytest

from lexoid.core.browse.session import GhostBrowserSession
from lexoid.core.ghost import GhostConfig


def test_session_starts_without_owned_tabs():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))

    assert session._owned_pages == {}
    assert session._retained_tabs == set()


class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_cdp_session_teardown_does_not_close_attached_browser():
    session = GhostBrowserSession(
        GhostConfig.from_kwargs({"cdp_url": "http://localhost:9222"})
    )
    browser = _FakeBrowser()
    playwright = _FakePlaywright()
    session._browser = browser
    session._playwright = playwright

    await session.__aexit__(None, None, None)

    assert browser.closed is False
    assert playwright.stopped is True


class _FakeNextControl:
    def __init__(self, visible: bool) -> None:
        self.visible = visible
        self.scrolled = False
        self.click_options: dict[str, int | bool] | None = None

    async def is_visible(self) -> bool:
        return self.visible

    async def is_disabled(self) -> bool:
        return False

    async def get_attribute(self, name: str) -> None:
        assert name == "aria-disabled"
        return None

    async def scroll_into_view_if_needed(self) -> None:
        self.scrolled = True

    async def click(self, **kwargs: int | bool) -> None:
        self.click_options = kwargs


class _FakeNextLocators:
    def __init__(self, controls: list[_FakeNextControl]) -> None:
        self.controls = controls

    async def count(self) -> int:
        return len(self.controls)

    def nth(self, index: int) -> _FakeNextControl:
        return self.controls[index]


class _FakePaginationPage:
    def __init__(self, controls: list[_FakeNextControl]) -> None:
        self.controls = controls

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str) -> _FakeNextLocators:
        assert selector
        return _FakeNextLocators(self.controls)

    async def wait_for_load_state(self, *args: object, **kwargs: object) -> None:
        return None

    async def wait_for_timeout(self, timeout: int) -> None:
        assert timeout == 500


@pytest.mark.asyncio
async def test_pagination_skips_hidden_next_control():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    hidden_control = _FakeNextControl(visible=False)
    visible_control = _FakeNextControl(visible=True)
    session._owned_pages["tab-1"] = _FakePaginationPage(
        [hidden_control, visible_control]
    )
    session._revisions["tab-1"] = 0

    advanced = await session.advance_to_next_result_page("tab-1")

    assert advanced is True
    assert hidden_control.click_options is None
    assert visible_control.scrolled is True
    assert visible_control.click_options == {"timeout": 5_000, "force": True}
    assert session._revisions["tab-1"] == 1
