"""Isolated session ownership tests using fakes instead of a browser."""

import pytest

from lexoid.core.browse.schemas import BrowserAction
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

    async def evaluate(self, script: str, *args: object) -> bool:
        assert "MutationObserver" in script
        return True

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


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


class _FakeSnapshotHandle:
    def __init__(self) -> None:
        self.clicked = False

    async def click(self, **kwargs: int) -> None:
        self.clicked = True

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True


class _FakeSnapshotLocatorItem:
    def __init__(self, handle: _FakeSnapshotHandle) -> None:
        self.handle = handle

    async def element_handle(self) -> _FakeSnapshotHandle:
        return self.handle


class _FakeSnapshotLocator:
    def __init__(self, handles: list[_FakeSnapshotHandle]) -> None:
        self.handles = handles

    async def evaluate_all(self, script: str) -> list[dict[str, object]]:
        assert "getBoundingClientRect" in script
        return [
            {
                "index": 0,
                "role": "button",
                "name": "Hidden",
                "tag": "button",
                "bbox_x": 0,
                "bbox_y": 0,
                "bbox_width": 0,
                "bbox_height": 0,
                "visible": False,
                "enabled": True,
            },
            {
                "index": 1,
                "role": "button",
                "name": "Search",
                "tag": "button",
                "bbox_x": 24,
                "bbox_y": 48,
                "bbox_width": 120,
                "bbox_height": 32,
                "visible": True,
                "enabled": True,
            },
        ]

    def nth(self, index: int) -> _FakeSnapshotLocatorItem:
        return _FakeSnapshotLocatorItem(self.handles[index])


class _FakeSnapshotPage:
    url = "https://example.com/search"

    def __init__(self) -> None:
        self.handles = [_FakeSnapshotHandle(), _FakeSnapshotHandle()]

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str) -> _FakeSnapshotLocator:
        assert selector == "button, a, input, select, textarea, [role]"
        return _FakeSnapshotLocator(self.handles)

    async def evaluate(self, script: str, *args: object) -> object:
        if "MutationObserver" in script:
            return True
        assert "innerWidth" in script
        return {"width": 1280, "height": 720, "scrollX": 0, "scrollY": 180}

    async def title(self) -> str:
        return "Search"

    async def wait_for_load_state(self, *args: object, **kwargs: object) -> None:
        return None

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


@pytest.mark.asyncio
async def test_snapshot_excludes_hidden_controls_and_executes_captured_handle():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0

    snapshot = await session.snapshot("tab-1")
    result = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot.snapshot_id, ref="e1")
    )

    assert [element.ref for element in snapshot.elements] == ["e1"]
    assert snapshot.elements[0].bbox_x == 24
    assert snapshot.elements[0].bbox_height == 32
    assert snapshot.viewport_width == 1280
    assert snapshot.scroll_y == 180
    assert result.success is True
    assert page.handles[0].clicked is False
    assert page.handles[1].clicked is True
