"""Isolated session ownership tests using fakes instead of a browser."""

import json

import pytest
from lexoid.core.browse.schemas import BrowserAction, BrowseTask
from lexoid.core.browse.session import GhostBrowserSession
from lexoid.core.browse.tools import BrowserToolset
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
    url = "https://example.com/search"

    def __init__(self, controls: list[_FakeNextControl]) -> None:
        self.controls = controls

    def is_closed(self) -> bool:
        return False

    async def title(self) -> str:
        return "Search"

    async def close(self) -> None:
        pass

    def on(self, event: str, handler: object) -> None:
        pass

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
        self.evaluated: list[tuple[str, tuple[object, ...]]] = []

    async def click(self, **kwargs: int) -> None:
        self.clicked = True

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def evaluate(self, script: str, *args: object) -> object:
        self.evaluated.append((script, args))
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
        self.evaluated: list[tuple[str, tuple[object, ...]]] = []

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str) -> _FakeSnapshotLocator:
        assert selector == "button, a, input, select, textarea, [role]"
        return _FakeSnapshotLocator(self.handles)

    async def evaluate(self, script: str, *args: object) -> object:
        self.evaluated.append((script, args))
        if "MutationObserver" in script:
            return True
        if "innerWidth" in script:
            return {"width": 1280, "height": 720, "scrollX": 0, "scrollY": 180}
        return True

    async def title(self) -> str:
        return "Search"

    async def wait_for_load_state(self, *args: object, **kwargs: object) -> None:
        return None

    async def wait_for_timeout(self, timeout: int) -> None:
        return None

    async def close(self) -> None:
        pass

    def on(self, event: str, handler: object) -> None:
        pass


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


class _FakeModalLocator:
    def __init__(self, handles: list[_FakeSnapshotHandle]) -> None:
        self.handles = handles

    async def evaluate_all(self, script: str) -> list[dict[str, object]]:
        assert "getBoundingClientRect" in script
        return [
            {
                "index": 0,
                "role": "button",
                "name": "Search",
                "tag": "button",
                "bbox_x": 100,
                "bbox_y": 100,
                "bbox_width": 80,
                "bbox_height": 30,
                "visible": False,
                "enabled": True,
                "in_modal": False,
            },
            {
                "index": 1,
                "role": "input",
                "name": "Min SF",
                "tag": "input",
                "bbox_x": 200,
                "bbox_y": 200,
                "bbox_width": 100,
                "bbox_height": 30,
                "visible": True,
                "enabled": True,
                "field_context": "Space Size",
                "input_type": "text",
                "in_modal": True,
            },
            {
                "index": 2,
                "role": "input",
                "name": "Min SF",
                "tag": "input",
                "bbox_x": 200,
                "bbox_y": 250,
                "bbox_width": 100,
                "bbox_height": 30,
                "visible": True,
                "enabled": True,
                "field_context": "Building Size",
                "input_type": "text",
                "in_modal": True,
            },
            {
                "index": 3,
                "role": "checkbox",
                "name": "Available",
                "tag": "input",
                "bbox_x": 200,
                "bbox_y": 300,
                "bbox_width": 20,
                "bbox_height": 20,
                "visible": True,
                "enabled": True,
                "checked": True,
                "input_type": "checkbox",
                "in_modal": True,
            },
            {
                "index": 4,
                "role": "button",
                "name": "Search",
                "tag": "button",
                "bbox_x": 200,
                "bbox_y": 350,
                "bbox_width": 80,
                "bbox_height": 30,
                "visible": True,
                "enabled": True,
                "in_modal": True,
            },
        ]

    def nth(self, index: int) -> _FakeSnapshotLocatorItem:
        return _FakeSnapshotLocatorItem(self.handles[index])


class _FakeModalPage(_FakeSnapshotPage):
    def __init__(self) -> None:
        super().__init__()
        self.handles = [_FakeSnapshotHandle() for _ in range(5)]

    def locator(self, selector: str) -> _FakeModalLocator:
        return _FakeModalLocator(self.handles)


@pytest.mark.asyncio
async def test_snapshot_prioritizes_modal_elements_and_captures_context_and_state():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeModalPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0

    snapshot = await session.snapshot("tab-1")
    refs = [e.ref for e in snapshot.elements]

    assert "e0" not in refs
    assert refs == ["e1", "e2", "e3", "e4"]

    e1 = next(e for e in snapshot.elements if e.ref == "e1")
    assert e1.name == "Min SF"
    assert e1.field_context == "Space Size"
    assert e1.input_type == "text"
    assert e1.in_modal is True

    e2 = next(e for e in snapshot.elements if e.ref == "e2")
    assert e2.name == "Min SF"
    assert e2.field_context == "Building Size"
    assert e2.input_type == "text"
    assert e2.in_modal is True

    e3 = next(e for e in snapshot.elements if e.ref == "e3")
    assert e3.checked is True
    assert e3.input_type == "checkbox"

    result = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot.snapshot_id, ref="e4")
    )
    assert result.success is True
    assert page.handles[0].clicked is False
    assert page.handles[4].clicked is True


@pytest.mark.asyncio
async def test_scroll_with_ref_targets_container_handle():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeModalPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0

    snapshot = await session.snapshot("tab-1")

    result = await session.execute(
        BrowserAction(
            kind="scroll",
            snapshot_id=snapshot.snapshot_id,
            ref="e1",
            text="down",
        )
    )
    assert result.success is True
    assert len(page.handles[1].evaluated) == 1
    script, args = page.handles[1].evaluated[0]
    assert "curr.scrollBy" in script
    assert args == (1,)

    snapshot2 = await session.snapshot("tab-1")
    result_window = await session.execute(
        BrowserAction(
            kind="scroll",
            snapshot_id=snapshot2.snapshot_id,
            text="up",
        )
    )
    assert result_window.success is True
    assert any("window.scrollBy" in call[0] for call in page.evaluated)


class _FakePopupPage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False
        self._handlers: dict[str, list] = {}

    def is_closed(self) -> bool:
        return self.closed

    async def title(self) -> str:
        return f"Title of {self.url}"

    async def close(self) -> None:
        self.closed = True

    async def wait_for_load_state(self, *args: object, **kwargs: object) -> None:
        return None

    async def evaluate(self, script: str, *args: object) -> object:
        if "innerWidth" in script:
            return {"width": 1280, "height": 720, "scrollX": 0, "scrollY": 0}
        return True

    def on(self, event: str, handler: object) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def locator(self, selector: str) -> _FakeSnapshotLocator:
        return _FakeSnapshotLocator([_FakeSnapshotHandle(), _FakeSnapshotHandle()])


class _FakePageWithPopup(_FakeSnapshotPage):
    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, list] = {}
        self.closed = False
        self.popup_to_trigger: _FakePopupPage | None = None

    def on(self, event: str, handler: object) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def trigger_popup(self, popup: _FakePopupPage) -> None:
        for handler in self._handlers.get("popup", []):
            handler(popup)

    async def close(self) -> None:
        self.closed = True


class _FakeClickTriggersPopupHandle(_FakeSnapshotHandle):
    def __init__(self, page: _FakePageWithPopup) -> None:
        super().__init__()
        self.page = page

    async def click(self, **kwargs: int) -> None:
        await super().click(**kwargs)
        if self.page.popup_to_trigger is not None:
            self.page.trigger_popup(self.page.popup_to_trigger)


@pytest.mark.asyncio
async def test_click_adopts_popup_and_prevents_duplicate_tabs():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    search_page = _FakePageWithPopup()
    search_page.handles = [
        _FakeSnapshotHandle(),
        _FakeClickTriggersPopupHandle(search_page),
    ]
    search_tab_id = session._register_page(search_page, "tab-search")

    popup1 = _FakePopupPage("https://example.com/listing/35626269/")
    search_page.popup_to_trigger = popup1

    snapshot1 = await session.snapshot(search_tab_id)
    result1 = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot1.snapshot_id, ref="e1")
    )

    assert result1.success is True
    assert result1.opened_tab_id is not None
    assert result1.opened_tab_id != search_tab_id
    assert result1.after_url == "https://example.com/listing/35626269/"
    assert "reused" not in result1.outcome
    assert result1.opened_tab_id in session._owned_pages
    assert popup1.closed is False
    opened_listing_tab_id = result1.opened_tab_id

    # Second click opens the same listing
    popup2 = _FakePopupPage("https://example.com/listing/35626269/")
    search_page.popup_to_trigger = popup2

    snapshot2 = await session.snapshot(search_tab_id)
    result2 = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot2.snapshot_id, ref="e1")
    )

    assert result2.success is True
    assert result2.opened_tab_id == opened_listing_tab_id
    assert result2.after_url == "https://example.com/listing/35626269/"
    assert "reused existing tab" in result2.outcome
    assert popup2.closed is True
    assert len(session._owned_pages) == 2

    # Cleanup closes both initial page and adopted popups
    await session.cleanup()
    assert search_page.closed is True
    assert popup1.closed is True


@pytest.mark.asyncio
async def test_fragment_routed_urls_are_not_merged_as_duplicates():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    search_page = _FakePageWithPopup()
    search_page.handles = [
        _FakeSnapshotHandle(),
        _FakeClickTriggersPopupHandle(search_page),
    ]
    search_tab_id = session._register_page(search_page, "tab-search")

    popup1 = _FakePopupPage("https://example.com/app/#/listing/1")
    search_page.popup_to_trigger = popup1

    snapshot1 = await session.snapshot(search_tab_id)
    result1 = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot1.snapshot_id, ref="e1")
    )
    assert result1.success is True
    tab1_id = result1.opened_tab_id

    popup2 = _FakePopupPage("https://example.com/app/#/listing/2")
    search_page.popup_to_trigger = popup2

    snapshot2 = await session.snapshot(search_tab_id)
    result2 = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot2.snapshot_id, ref="e1")
    )
    assert result2.success is True
    tab2_id = result2.opened_tab_id
    assert tab2_id != tab1_id
    assert result2.after_url == "https://example.com/app/#/listing/2"
    assert "reused" not in result2.outcome
    assert len(session._owned_pages) == 3


@pytest.mark.asyncio
async def test_popup_opened_outside_action_is_owned_and_cleaned_up():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    main_page = _FakePageWithPopup()
    session._register_page(main_page, "tab-main")

    popup = _FakePopupPage("https://example.com/external")
    main_page.trigger_popup(popup)

    # Popup was immediately owned upon trigger
    assert len(session._owned_pages) == 2
    assert popup.closed is False

    await session.cleanup()
    assert main_page.closed is True
    assert popup.closed is True


@pytest.mark.asyncio
async def test_popup_from_other_tab_not_consumed_by_unrelated_tab_action():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page1 = _FakePageWithPopup()
    page1.handles = [_FakeSnapshotHandle(), _FakeSnapshotHandle()]
    tab1_id = session._register_page(page1, "tab-1")

    page2 = _FakePageWithPopup()
    page2.handles = [_FakeSnapshotHandle(), _FakeClickTriggersPopupHandle(page2)]
    tab2_id = session._register_page(page2, "tab-2")

    # page1 triggers a popup outside of execute
    popup1 = _FakePopupPage("https://example.com/from-page1")
    page1.trigger_popup(popup1)

    # Now execute an action on tab2 that does not trigger a popup
    page2.popup_to_trigger = None
    snapshot2 = await session.snapshot(tab2_id)
    result2 = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot2.snapshot_id, ref="e1")
    )
    assert result2.success is True
    # result2 should NOT have consumed tab1's popup
    assert result2.opened_tab_id is None
    assert len(session._pending_popups) == 1


@pytest.mark.asyncio
async def test_toolset_active_tab_tracking_and_switching():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    search_page = _FakePageWithPopup()
    search_page.handles = [
        _FakeSnapshotHandle(),
        _FakeClickTriggersPopupHandle(search_page),
    ]
    search_tab_id = session._register_page(search_page, "tab-search")

    popup = _FakePopupPage("https://example.com/listing/1")
    search_page.popup_to_trigger = popup

    traces = []

    async def emit_trace(trace):
        traces.append(trace)

    task = BrowseTask(
        seed_urls=["https://example.com/search"],
        subject="test",
        allowed_domains=["example.com"],
    )
    toolset = BrowserToolset(session, task, search_tab_id, emit_trace)
    assert toolset.tab_id == search_tab_id

    # Clicking the link switches toolset.tab_id to the popup tab
    await toolset.click("e1")
    assert toolset.tab_id != search_tab_id
    listing_tab_id = toolset.tab_id

    # list_tabs shows both tabs with active indicator
    tabs_raw = await toolset.list_tabs()
    tabs = json.loads(tabs_raw)
    assert len(tabs) == 2
    listing_entry = next(t for t in tabs if t["tab_id"] == listing_tab_id)
    assert listing_entry["active"] is True
    search_entry = next(t for t in tabs if t["tab_id"] == search_tab_id)
    assert search_entry["active"] is False

    # switch_tab back to search tab
    switch_res = json.loads(await toolset.switch_tab(search_tab_id))
    assert switch_res["success"] is True
    assert toolset.tab_id == search_tab_id

    # switch_tab with invalid id fails and preserves active tab
    invalid_res = json.loads(await toolset.switch_tab("tab-nonexistent"))
    assert invalid_res["success"] is False
    assert toolset.tab_id == search_tab_id


@pytest.mark.asyncio
async def test_browser_toolset_blocks_off_domain_popup():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    search_page = _FakePageWithPopup()
    search_page.handles = [
        _FakeSnapshotHandle(),
        _FakeClickTriggersPopupHandle(search_page),
    ]
    search_tab_id = session._register_page(search_page, "tab-search")

    off_domain_popup = _FakePopupPage("https://evil.example/malicious")
    search_page.popup_to_trigger = off_domain_popup

    task = BrowseTask(
        seed_urls=["https://example.com/"],
        subject="test",
        allowed_domains=["example.com"],
    )
    events = []

    async def emit_trace(trace: object) -> None:
        events.append(trace)

    toolset = BrowserToolset(session, task, search_tab_id, emit_trace)

    raw_res = await toolset.click("e1")
    res = json.loads(raw_res)
    assert res["result"]["success"] is False
    assert res["result"]["error_code"] == "policy_denied"
    assert "outside allowlist" in res["result"]["outcome"]
    assert off_domain_popup.closed is True
    assert toolset.tab_id == search_tab_id
