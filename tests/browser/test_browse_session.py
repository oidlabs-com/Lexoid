"""Isolated session ownership tests using fakes instead of a browser."""

import json

import pytest
from lexoid.core.browse import session as browse_session
from lexoid.core.browse.schemas import (
    BrowserAction,
    BrowserActionResult,
    BrowseTask,
    ElementRef,
    InferredSeed,
    MediaState,
    SourceScope,
)
from lexoid.core.browse.session import (
    _AD_SKIP_SELECTOR,
    BrowserDriverError,
    GhostBrowserSession,
)
from lexoid.core.browse.tools import BrowserToolset
from lexoid.core.ghost import GhostConfig


@pytest.fixture(autouse=True)
def _no_action_pacing(monkeypatch):
    monkeypatch.setattr(browse_session, "_ACTION_GAP_S", (0.0, 0.0))
    monkeypatch.setattr(browse_session, "_KEY_GAP_S", (0.0, 0.0))


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


@pytest.mark.asyncio
async def test_restore_page_returns_owned_tab_to_allowlisted_url():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakePageWithPopup()
    page.url = "https://off-scope.example/"
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 2

    restored = await session.restore_page("tab-1", "https://google.com/search?q=recipe")

    assert restored.url == "https://google.com/search?q=recipe"
    assert session._revisions["tab-1"] == 3


class _FakeSettlePage:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.evaluate_args: tuple[object, ...] = ()

    async def wait_for_load_state(self, *args: object, **kwargs: object) -> None:
        return None

    async def evaluate(self, script: str, *args: object) -> object:
        assert "MutationObserver" in script
        self.evaluate_args = args
        if self.outcome == "hang":
            import asyncio

            await asyncio.sleep(10)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.asyncio
async def test_text_wait_filters_visible_matches_before_first_and_does_not_settle(
    monkeypatch,
):
    session = GhostBrowserSession(GhostConfig.from_kwargs({"timeout_ms": 30_000}))
    page = _FakeSnapshotPage()
    tab_id = session._register_page(page)
    queries = []

    class _WaitLocator:
        def locator(self, selector):
            queries.append(selector)
            return self

        @property
        def first(self):
            queries.append("first")
            return self

        async def wait_for(self, **kwargs):
            queries.append(kwargs)

    def get_by_text(text, *, exact):
        queries.append((text, exact))
        return _WaitLocator()

    async def settle(_page):
        pytest.fail("A wait should not trigger another settle")

    monkeypatch.setattr(page, "get_by_text", get_by_text, raising=False)
    monkeypatch.setattr(session, "_settle_page", settle)
    snapshot = await session.snapshot(tab_id)
    result = await session.execute(
        BrowserAction(kind="wait", text="Skip", snapshot_id=snapshot.snapshot_id)
    )
    assert result.success
    assert queries == [
        ("Skip", False),
        "visible=true",
        "first",
        {"state": "visible", "timeout": 5_500},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected", "log_fragment"),
    [
        ("quiet", "quiet", None),
        ("max_wait", "max_wait", None),
        (RuntimeError("Execution context was destroyed"), "error", "failed"),
        ("hang", "timeout", "did not return"),
    ],
)
async def test_settle_is_bounded_and_reports_status(
    monkeypatch, outcome, expected, log_fragment
):
    session = GhostBrowserSession(GhostConfig.from_kwargs({"timeout_ms": 60_000}))
    monkeypatch.setattr(session, "_settle_max_wait_ms", 10)
    monkeypatch.setattr(browse_session, "_SETTLE_GRACE_S", 0.05)
    messages: list[str] = []
    monkeypatch.setattr(browse_session.logger, "debug", messages.append)
    page = _FakeSettlePage(outcome)

    status = await session._settle_page(page)

    assert status == expected
    assert page.evaluate_args == ({"idleMs": 500, "maxMs": 10},)
    if log_fragment is None:
        assert messages == []
    else:
        assert any(log_fragment in message for message in messages)


class _FakeNavigatingPage:
    def __init__(self, error: Exception, failures: int) -> None:
        self.error = error
        self.failures = failures
        self.calls = 0

    def is_closed(self) -> bool:
        return False

    async def content(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return "<html>done</html>"


@pytest.mark.asyncio
async def test_content_retries_after_patchright_navigation_race(monkeypatch):
    patchright_api = pytest.importorskip("patchright.async_api")
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    settled: list[object] = []

    async def settle(page):
        settled.append(page)
        return "quiet"

    monkeypatch.setattr(session, "_settle_page", settle)
    error = patchright_api.Error(
        "Page.content: Unable to retrieve content because the page is navigating "
        "and changing the content."
    )
    page = _FakeNavigatingPage(error, failures=1)
    session._owned_pages["tab-1"] = page

    assert await session.content("tab-1") == "<html>done</html>"
    assert settled == [page]

    stuck = _FakeNavigatingPage(error, failures=10)
    session._owned_pages["tab-2"] = stuck
    with pytest.raises(patchright_api.Error):
        await session.content("tab-2")
    assert stuck.calls == browse_session._READ_ATTEMPTS


class _FakeHighlightHandle:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[object] = []

    async def scroll_into_view_if_needed(self, **kwargs: object) -> None:
        self.calls.append("scroll")

    async def evaluate(self, script: str, *args: object) -> None:
        if self.fail:
            raise RuntimeError("element detached")
        self.calls.append(args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"headless": True}, []),
        ({"headless": False}, []),
        ({"cdp_url": "http://localhost:9222"}, []),
        ({"headless": False, "highlight": True}, ["scroll", (0,)]),
        ({"headless": True, "highlight": True}, []),
        (
            {"cdp_url": "http://localhost:9222", "highlight": True},
            ["scroll", (0,)],
        ),
    ],
)
async def test_highlight_only_when_browser_is_visible(monkeypatch, options, expected):
    monkeypatch.delenv("LEXOID_DEBUG_HIGHLIGHT", raising=False)
    monkeypatch.setattr(browse_session, "_HIGHLIGHT_MS", 0)
    session = GhostBrowserSession(GhostConfig.from_kwargs(options))
    handle = _FakeHighlightHandle()

    await session._highlight(handle)

    assert handle.calls == expected
    await session._highlight(_FakeHighlightHandle(fail=True))


def test_highlight_debug_environment_can_be_overridden(monkeypatch):
    monkeypatch.setenv("LEXOID_DEBUG_HIGHLIGHT", "1")
    assert GhostConfig.from_kwargs(True).highlight is True
    assert GhostConfig.from_kwargs({"highlight": False}).highlight is False


def test_settle_max_wait_is_independent_of_navigation_timeout():
    session = GhostBrowserSession(GhostConfig.from_kwargs({"timeout_ms": 60_000}))

    assert session._settle_max_wait_ms == browse_session._SETTLE_MAX_WAIT_MS


@pytest.mark.asyncio
async def test_action_pacing_waits_only_after_recent_action(monkeypatch):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    session._action_gap_s = (1.0, 1.0)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(browse_session.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(browse_session.time, "monotonic", lambda: 100.0)

    await session._pace_action()
    session._last_action_at = 99.8
    await session._pace_action()
    session._last_action_at = 98.0
    await session._pace_action()

    assert sleeps == [pytest.approx(0.8)]


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
    def __init__(self, value: str = "") -> None:
        self.clicked = False
        self.click_kwargs: dict[str, object] = {}
        self.value = value
        self.evaluated: list[tuple[str, tuple[object, ...]]] = []

    async def click(self, **kwargs: object) -> None:
        self.clicked = True
        self.click_kwargs = kwargs

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def bounding_box(self) -> dict[str, float]:
        return {"x": 24, "y": 48, "width": 120, "height": 32}

    async def scroll_into_view_if_needed(self, **kwargs: object) -> None:
        return None

    async def input_value(self, **kwargs: object) -> str:
        return self.value

    async def evaluate(self, script: str, *args: object) -> object:
        self.evaluated.append((script, args))
        if "innerHeight" in script:
            return 400
        return True


class _FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float, int]] = []
        self.wheels: list[tuple[float, float]] = []

    async def move(self, x: float, y: float, *, steps: int = 1) -> None:
        self.moves.append((x, y, steps))

    async def wheel(self, delta_x: float, delta_y: float) -> None:
        self.wheels.append((delta_x, delta_y))


class _FakeKeyboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def type(self, text: str, **kwargs: object) -> None:
        self.events.append(("type", text))

    async def press(self, key: str, **kwargs: object) -> None:
        self.events.append(("press", key))

    @property
    def typed(self) -> str:
        return "".join(text for kind, text in self.events if kind == "type")


class _FakePasswordHandle(_FakeSnapshotHandle):
    async def get_attribute(self, name: str) -> str | None:
        assert name == "type"
        return "password"


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

    async def element_handles(self) -> list[_FakeSnapshotHandle]:
        return list(self.handles)

    async def count(self) -> int:
        return 0


class _FakePasswordLocator(_FakeSnapshotLocator):
    async def evaluate_all(self, script: str) -> list[dict[str, object]]:
        assert "getBoundingClientRect" in script
        return [
            {
                "index": 0,
                "role": "textbox",
                "name": "Password",
                "tag": "input",
                "bbox_x": 24,
                "bbox_y": 48,
                "bbox_width": 120,
                "bbox_height": 32,
                "visible": True,
                "enabled": True,
                "input_type": "password",
            }
        ]


class _FakeSnapshotPage:
    url = "https://example.com/search"
    frames: list[object] = []

    def __init__(self) -> None:
        self.handles = [_FakeSnapshotHandle(), _FakeSnapshotHandle()]
        self.evaluated: list[tuple[str, tuple[object, ...]]] = []
        self.front_count = 0
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()

    def is_closed(self) -> bool:
        return False

    async def bring_to_front(self) -> None:
        self.front_count += 1

    def locator(self, selector: str) -> _FakeSnapshotLocator:
        assert selector in {
            "button, a, input, select, textarea, [role]",
            "#movie_player.ad-showing",
        }
        return _FakeSnapshotLocator(self.handles)

    async def evaluate(self, script: str, *args: object) -> object:
        self.evaluated.append((script, args))
        if "MutationObserver" in script:
            return True
        if script == "() => window.innerHeight":
            return 720
        if "innerWidth" in script:
            return {
                "width": 1280,
                "height": 720,
                "scrollX": 0,
                "scrollY": 180,
                "media_state": [
                    {
                        "media_type": "video",
                        "paused": False,
                        "current_time": 1.5,
                        "duration": 600,
                        "ended": False,
                        "ready_state": 4,
                    }
                ],
            }
        if "querySelectorAll" in script:
            return [
                {
                    "media_type": "video",
                    "paused": False,
                    "current_time": 1.5,
                    "duration": 600,
                    "ended": False,
                    "ready_state": 4,
                }
            ]
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


class _FakePasswordPage(_FakeSnapshotPage):
    def __init__(self) -> None:
        super().__init__()
        self.handles = [_FakePasswordHandle()]

    def locator(self, selector: str) -> _FakePasswordLocator:
        assert selector == "button, a, input, select, textarea, [role]"
        return _FakePasswordLocator(self.handles)


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
    assert snapshot.media_state == [
        MediaState(
            media_type="video",
            paused=False,
            current_time=1.5,
            duration=600,
            ended=False,
            ready_state=4,
        )
    ]
    assert result.success is True
    assert page.handles[0].clicked is False
    assert page.handles[1].clicked is True


@pytest.mark.asyncio
async def test_snapshot_falls_back_to_indexed_handles_when_dom_changes(monkeypatch):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0

    async def changed_handles(locator):
        return locator.handles[:1]

    monkeypatch.setattr(_FakeSnapshotLocator, "element_handles", changed_handles)
    snapshot = await session.snapshot("tab-1")
    result = await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot.snapshot_id, ref="e1")
    )

    assert [element.ref for element in snapshot.elements] == ["e1"]
    assert result.success is True
    assert page.handles[1].clicked is True


@pytest.mark.asyncio
async def test_element_actions_fail_fast_and_history_waits_for_dom(monkeypatch):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0
    calls: list[tuple[str, dict[str, object]]] = []

    async def click(**kwargs):
        calls.append(("click", kwargs))

    async def history(name, **kwargs):
        calls.append((name, kwargs))

    monkeypatch.setattr(page.handles[1], "click", click)
    page.go_back = lambda **kwargs: history("back", **kwargs)
    page.reload = lambda **kwargs: history("refresh", **kwargs)

    for kind in ("click", "back", "refresh"):
        snapshot = await session.snapshot("tab-1")
        result = await session.execute(
            BrowserAction(kind=kind, snapshot_id=snapshot.snapshot_id, ref="e1")
        )
        assert result.success is True

    timeout = session._config.timeout_ms
    assert calls[0][1]["timeout"] == 10_000
    assert calls[1:] == [
        ("back", {"wait_until": "domcontentloaded", "timeout": timeout}),
        ("refresh", {"wait_until": "domcontentloaded", "timeout": timeout}),
    ]


@pytest.mark.asyncio
async def test_click_travels_to_jittered_point_and_holds_button():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0
    snapshot = await session.snapshot("tab-1")

    await session.execute(
        BrowserAction(kind="click", snapshot_id=snapshot.snapshot_id, ref="e1")
    )

    options = page.handles[1].click_kwargs
    low_steps, high_steps = browse_session._POINTER_STEPS
    low_press, high_press = browse_session._PRESS_MS
    assert low_steps <= options["steps"] <= high_steps
    assert low_press <= options["delay"] <= high_press
    assert 0.3 * 120 <= options["position"]["x"] <= 0.7 * 120
    assert 0.3 * 32 <= options["position"]["y"] <= 0.7 * 32


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing", "expected_events"),
    [
        ("", [("type", "4"), ("type", "2")]),
        (
            "old",
            [
                ("press", "ControlOrMeta+A"),
                ("press", "Backspace"),
                ("type", "4"),
                ("type", "2"),
            ],
        ),
    ],
)
async def test_type_clicks_clears_existing_value_and_types_per_key(
    existing, expected_events
):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    page.handles[1].value = existing
    page.handles[1].get_attribute = lambda name: _async_value("text")
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0
    snapshot = await session.snapshot("tab-1")

    result = await session.execute(
        BrowserAction(
            kind="type", snapshot_id=snapshot.snapshot_id, ref="e1", text="42"
        )
    )

    assert result.success is True
    assert page.handles[1].clicked is True
    assert page.keyboard.events == expected_events


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_capture_open_tabs_records_media_state_before_cleanup():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0

    tabs = await session.capture_open_tabs()

    assert len(tabs) == 1
    assert tabs[0].url == page.url
    assert tabs[0].media_state[0].paused is False
    assert tabs[0].media_state[0].current_time == 1.5


@pytest.mark.asyncio
async def test_password_field_typing_warns_but_still_fills(monkeypatch):
    warnings: list[str] = []

    class _Logger:
        def warning(self, message: str, *args: str) -> None:
            warnings.append(message.format(*args))

    monkeypatch.setattr(browse_session, "logger", _Logger())
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakePasswordPage()
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0
    snapshot = await session.snapshot("tab-1")

    result = await session.execute(
        BrowserAction(
            kind="type",
            snapshot_id=snapshot.snapshot_id,
            ref="e0",
            text="secret-value",
        )
    )

    assert result.success is True
    assert page.keyboard.typed == "secret-value"
    assert len(warnings) == 1
    assert "experimental and not yet validated" in warnings[0]
    assert "tab=tab-1" in warnings[0]
    assert "ref=e0" in warnings[0]
    assert "secret-value" not in warnings[0]


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

    async def element_handles(self) -> list[_FakeSnapshotHandle]:
        return list(self.handles)


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


class _FakeFrameElement:
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    async def is_visible(self) -> bool:
        return self.visible


class _FakeFrame:
    def __init__(self, url: str, visible: bool = True) -> None:
        self.url = url
        self.element = _FakeFrameElement(visible)

    async def frame_element(self) -> _FakeFrameElement:
        return self.element


class _FakeVerificationPage(_FakeSnapshotPage):
    def __init__(self, frames: list[_FakeFrame], solved: bool) -> None:
        super().__init__()
        self.frames = frames
        self.solved = solved

    async def evaluate(self, script: str, *args: object) -> object:
        if "captcha-response" in script:
            return self.solved
        return await super().evaluate(script, *args)


_HCAPTCHA = (
    "https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha.html#frame={}&id=0"
)
_RECAPTCHA = "https://www.google.com/recaptcha/api2/{}?k=key&size={}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frames", "solved", "expected"),
    [
        ([_FakeFrame(_HCAPTCHA.format("challenge"))], True, "hcaptcha"),
        ([_FakeFrame(_HCAPTCHA.format("challenge"), visible=False)], False, None),
        ([_FakeFrame(_HCAPTCHA.format("checkbox"))], False, "hcaptcha"),
        ([_FakeFrame(_HCAPTCHA.format("checkbox"))], True, None),
        ([_FakeFrame(_RECAPTCHA.format("anchor", "invisible"))], False, None),
        ([_FakeFrame(_RECAPTCHA.format("anchor", "normal"))], False, "recaptcha"),
        ([_FakeFrame(_RECAPTCHA.format("bframe", "normal"))], True, "recaptcha"),
        ([_FakeFrame("https://example.com/embed")], False, None),
    ],
)
async def test_verification_challenge_reports_only_visible_unsolved_challenges(
    frames, solved, expected
):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    session._owned_pages["tab-1"] = _FakeVerificationPage(frames, solved)

    assert await session.verification_challenge("tab-1") == expected


@pytest.mark.asyncio
async def test_select_on_editable_combobox_types_to_filter_before_choosing():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeModalPage()
    option = _FakeSnapshotHandle()
    roles: list[tuple[str, str]] = []

    class _Options:
        first = option

    def get_by_role(role, name):
        roles.append((role, name))
        return _Options()

    page.get_by_role = get_by_role
    session._owned_pages["tab-1"] = page
    session._revisions["tab-1"] = 0
    snapshot = await session.snapshot("tab-1")

    result = await session.execute(
        BrowserAction(
            kind="select", snapshot_id=snapshot.snapshot_id, ref="e1", text="MX"
        )
    )

    assert result.success is True
    assert page.handles[1].clicked is True
    assert page.keyboard.typed == "MX"
    assert roles == [("option", "MX")]
    assert option.clicked is True
    assert "steps" in option.click_kwargs


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
    assert len(page.mouse.moves) == 1
    assert page.mouse.wheels == [(0, 400 * 0.8)]

    snapshot2 = await session.snapshot("tab-1")
    result_window = await session.execute(
        BrowserAction(
            kind="scroll",
            snapshot_id=snapshot2.snapshot_id,
            text="up",
        )
    )
    assert result_window.success is True
    assert page.mouse.wheels[-1] == (0, -720 * 0.8)
    assert not any("scrollBy" in call[0] for call in page.evaluated)


class _FakePopupPage:
    frames: list[object] = []

    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False
        self.front_count = 0
        self._handlers: dict[str, list] = {}

    def is_closed(self) -> bool:
        return self.closed

    async def bring_to_front(self) -> None:
        self.front_count += 1

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

    async def goto(self, url: str, **kwargs: object) -> None:
        self.url = url


class _FakePageContext:
    def __init__(self) -> None:
        self.pages: list[_FakePageWithPopup] = []

    async def new_page(self) -> _FakePageWithPopup:
        page = _FakePageWithPopup()
        self.pages.append(page)
        return page


class _FakeClickTriggersPopupHandle(_FakeSnapshotHandle):
    def __init__(self, page: _FakePageWithPopup) -> None:
        super().__init__()
        self.page = page

    async def click(self, **kwargs: int) -> None:
        await super().click(**kwargs)
        if self.page.popup_to_trigger is not None:
            self.page.trigger_popup(self.page.popup_to_trigger)


@pytest.mark.asyncio
@pytest.mark.parametrize("popup", [False, True])
@pytest.mark.parametrize(
    ("source", "href", "destination", "admitted"),
    [
        (
            "https://www.google.com/search",
            "https://www.allrecipes.com/recipe/1",
            "https://www.allrecipes.com/recipe/1",
            True,
        ),
        (
            "https://www.bing.com/search",
            "https://www.allrecipes.com/recipe/1",
            "https://www.allrecipes.com/recipe/1",
            True,
        ),
        (
            "https://www.duckduckgo.com/",
            "https://www.allrecipes.com/recipe/1",
            "https://www.allrecipes.com/recipe/1",
            True,
        ),
        (
            "https://search.brave.com/search",
            "https://www.allrecipes.com/recipe/1",
            "https://www.allrecipes.com/recipe/1",
            True,
        ),
        (
            "https://www.google.com/search",
            "https://www.google.com/goto?url=opaque",
            "https://www.allrecipes.com/recipe/1",
            True,
        ),
        (
            "https://www.google.com/search",
            "https://www.allrecipes.com/recipe/1",
            "https://unrelated.com/",
            False,
        ),
        (
            "https://www.google.com/search",
            "https://www.google.com/redirect?url=opaque",
            "https://unrelated.com/",
            False,
        ),
        (
            "https://www.google.com/search",
            None,
            "https://www.allrecipes.com/recipe/1",
            False,
        ),
        (
            "https://example.com/search",
            "https://www.allrecipes.com/recipe/1",
            "https://www.allrecipes.com/recipe/1",
            False,
        ),
    ],
)
async def test_toolset_search_discovery(
    monkeypatch, popup, source, href, destination, admitted
):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakePageWithPopup()
    page.url = source
    tab_id = session._register_page(page, "tab-search")
    original_entries = _FakeSnapshotLocator.evaluate_all

    async def link_entries(locator, script):
        entries = await original_entries(locator, script)
        entries[1].update({"tag": "a", "role": "link", "href": href})
        return entries

    async def click(**kwargs):
        if popup:
            page.trigger_popup(_FakePopupPage(destination))
        else:
            page.url = destination

    monkeypatch.setattr(_FakeSnapshotLocator, "evaluate_all", link_entries)
    monkeypatch.setattr(page.handles[1], "click", click)
    traces = []

    async def emit(trace):
        traces.append(trace)

    task = BrowseTask(
        seed_urls=["https://www.google.com/" if admitted else source],
        subject="Find a recipe",
        allowed_domains=["google.com"] if admitted else ["google.com", "example.com"],
    )
    toolset = BrowserToolset(session, task, tab_id, emit)
    response = json.loads(await toolset.click("e1"))

    assert response["result"]["success"] is admitted
    assert ("allrecipes.com" in task.allowed_domains) is admitted
    action_trace = next(trace for trace in traces if trace.event == "action")
    assert action_trace.metadata.get("discovered_domain") == (
        "allrecipes.com" if admitted else None
    )
    if not popup and not admitted:
        assert page.url == source
        assert not toolset.is_quarantined
        assert "restored previous page" in response["result"]["outcome"]
        assert response["result"]["warnings"] == [
            "Restored the allowlisted source page."
        ]
    if admitted:
        assert not toolset.is_quarantined
        assert action_trace.metadata["discovery_check"]["initial_domains"] == [
            "google.com"
        ]
        assert (
            "bing.com"
            in action_trace.metadata["discovery_check"]["fallback_search_domains"]
        )
        denied = json.loads(await toolset.navigate("https://unrelated.com/"))
        assert denied["result"]["success"] is False
        # A second outbound click from the discovered site cannot expand scope.
        href = "https://unrelated.com/"
        destination = href

        async def outbound_click(action):
            active_page = session._owned_pages[toolset.tab_id]
            assert isinstance(active_page, (_FakePageWithPopup, _FakePopupPage))
            active_page.url = destination
            return BrowserActionResult(
                success=True, outcome="clicked", after_url=destination
            )

        monkeypatch.setattr(session, "execute", outbound_click)
        toolset._snapshot = None
        denied = json.loads(await toolset.click("e1"))
        assert denied["result"]["success"] is False
        assert "unrelated.com" not in task.allowed_domains


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "source_scope",
        "source_url",
        "source_domains",
        "destination_url",
        "evidence",
        "allowed",
    ),
    [
        (
            "search_provider_only",
            "https://www.google.com/search?q=filing",
            ["google.com"],
            "https://www.sec.gov/Archives/edgar/data/1",
            "Only search using Google",
            True,
        ),
        (
            "domain_only",
            "https://www.sec.gov/",
            ["sec.gov"],
            "https://www.google.com/search?q=filing",
            "Only use sec.gov",
            False,
        ),
        (
            "domain_only",
            "https://www.google.com/search?q=filing",
            ["google.com", "sec.gov"],
            "https://www.sec.gov/Archives/edgar/data/1",
            "Only use Google and sec.gov",
            True,
        ),
        (
            "domain_only",
            "https://www.google.com/search?q=filing",
            ["google.com", "sec.gov"],
            "https://www.reuters.com/markets/filing",
            "Only use Google and sec.gov",
            False,
        ),
    ],
)
async def test_restricted_scope_separates_provider_from_result_sources(
    monkeypatch,
    source_scope,
    source_url,
    source_domains,
    destination_url,
    evidence,
    allowed,
):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakePageWithPopup()
    page.url = source_url
    tab_id = session._register_page(page, "tab-restricted")
    original_entries = _FakeSnapshotLocator.evaluate_all

    async def link_entries(locator, script):
        entries = await original_entries(locator, script)
        entries[1].update(
            {
                "tag": "a",
                "role": "link",
                "href": destination_url,
            }
        )
        return entries

    async def click(**kwargs):
        page.url = destination_url

    monkeypatch.setattr(_FakeSnapshotLocator, "evaluate_all", link_entries)
    monkeypatch.setattr(page.handles[1], "click", click)
    traces = []

    async def emit(trace):
        traces.append(trace)

    task = BrowseTask(
        seed_urls=[source_url],
        subject="Find filing",
        allowed_domains=list(source_domains),
        source_scope=SourceScope(mode=source_scope, evidence=evidence),
    )
    toolset = BrowserToolset(session, task, tab_id, emit)
    assert toolset.fallback_search_domains == []

    response = json.loads(await toolset.click("e1"))

    assert response["result"]["success"] is allowed
    destination_domain = (
        destination_url.split("//", 1)[1].split("/", 1)[0].removeprefix("www.")
    )
    assert (destination_domain in task.allowed_domains) is allowed
    action_trace = next(trace for trace in traces if trace.event == "action")
    assert action_trace.metadata["discovery_check"]["source_scope"] == {
        "mode": source_scope,
        "evidence": evidence,
    }


class _FakeAdPage:
    def __init__(self, url: str, ad_showing: bool, skippable: bool) -> None:
        self.url = url
        self.ad_showing = ad_showing
        self.skippable = skippable
        self.clicks: list[str] = []

    def is_closed(self) -> bool:
        return False

    def on(self, event: str, handler: object) -> None:
        pass

    def locator(self, selector: str):
        page = self

        class _Locator:
            first = None

            async def count(self) -> int:
                return int(page.ad_showing)

            async def click(self, timeout: int) -> None:
                if not page.skippable:
                    raise BrowserDriverError[0]("Timeout exceeded")
                page.clicks.append(selector)

        locator = _Locator()
        locator.first = locator
        return locator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "ad_showing", "skippable", "skipped"),
    [
        ("https://www.youtube.com/watch?v=x", True, True, True),
        ("https://www.youtube.com/watch?v=x", False, True, False),
        ("https://www.youtube.com/watch?v=x", True, False, False),
        ("https://example.com/watch?v=x", True, True, False),
    ],
    ids=["skippable", "no-ad", "unskippable", "not-youtube"],
)
async def test_skip_ad_clicks_only_a_visible_youtube_skip_button(
    url, ad_showing, skippable, skipped
):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeAdPage(url, ad_showing, skippable)
    tab_id = session._register_page(page)

    assert await session.skip_ad(tab_id) is skipped
    assert page.clicks == ([_AD_SKIP_SELECTOR] if skipped else [])
    assert session._revisions[tab_id] == int(skipped)


@pytest.mark.asyncio
@pytest.mark.parametrize("skipped", [True, False])
async def test_observe_skips_ad_before_snapshot(monkeypatch, skipped):
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakeSnapshotPage()
    page.url = "https://www.youtube.com/watch?v=x"
    tab_id = session._register_page(page)
    calls = []
    traces = []

    async def skip_ad(tab):
        calls.append(("skip", tab))
        return skipped

    original_snapshot = session.snapshot

    async def snapshot(tab):
        calls.append(("snapshot", tab))
        return await original_snapshot(tab)

    async def emit(trace):
        traces.append(trace)

    monkeypatch.setattr(session, "skip_ad", skip_ad)
    monkeypatch.setattr(session, "snapshot", snapshot)
    task = BrowseTask(
        seed_urls=[page.url], subject="Watch video", allowed_domains=["youtube.com"]
    )
    toolset = BrowserToolset(session, task, tab_id, emit)
    await toolset.observe()

    assert calls == [("skip", tab_id), ("snapshot", tab_id)]
    actions = [trace for trace in traces if trace.event == "action"]
    assert [trace.metadata for trace in actions] == (
        [{"automatic_ad_skip": True}] if skipped else []
    )
    assert toolset.action_count == int(skipped)
    assert toolset.successful_action_count == 0


@pytest.mark.asyncio
async def test_open_tab_opens_only_allowlisted_url_and_switches_active_tab():
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    root = _FakePageWithPopup()
    root.url = "https://google.com/"
    root_id = session._register_page(root, "tab-root")
    context = _FakePageContext()
    session._context = context
    traces = []

    async def emit(trace):
        traces.append(trace)

    task = BrowseTask(
        seed_urls=["https://google.com/"],
        subject="Inspect a product and a video",
        allowed_domains=["google.com", "youtube.com"],
    )
    toolset = BrowserToolset(session, task, root_id, emit)

    response = json.loads(await toolset.open_tab("https://www.youtube.com/"))

    assert response["result"]["success"] is True
    assert response["result"]["opened_tab_id"] == toolset.tab_id
    assert toolset.tab_id != root_id
    assert len(session._owned_pages) == 2
    assert response["observation"]["url"] == "https://www.youtube.com/"
    action_trace = next(trace for trace in traces if trace.event == "action")
    assert action_trace.action.kind == "open_tab"
    assert action_trace.result.opened_tab_id == toolset.tab_id

    denied = json.loads(await toolset.open_tab("https://unrelated.example/"))
    assert denied["result"]["success"] is False
    assert denied["result"]["error_code"] == "policy_denied"
    assert len(session._owned_pages) == 2

    youtube_id = toolset.tab_id
    await toolset.switch_tab(root_id)
    await toolset.open_tab("https://www.youtube.com/")
    assert toolset.tab_id == youtube_id
    assert len(session._owned_pages) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("inferred", [False, True])
@pytest.mark.parametrize("search_enabled", [False, True])
async def test_search_fallback_navigation_preserves_seed_provenance(
    monkeypatch, inferred, search_enabled
):
    seed = "https://www.google.com/" if search_enabled else "https://example.com/"
    domain = "google.com" if search_enabled else "example.com"
    session = GhostBrowserSession(GhostConfig.from_kwargs(True))
    page = _FakePageWithPopup()
    page.url = seed
    tab_id = session._register_page(page, "tab-search")
    task = BrowseTask(
        seed_urls=[] if inferred else [seed],
        inferred_seeds=[InferredSeed(url=seed, source_text=domain)] if inferred else [],
        subject="Find a recipe",
        allowed_domains=[domain],
    )
    original_seeds = task.model_dump(include={"seed_urls", "inferred_seeds"})
    traces = []
    executed = []

    async def emit(trace):
        traces.append(trace)

    async def execute(action):
        executed.append(action)
        assert action.url is not None
        before_url = page.url
        page.url = action.url
        return BrowserActionResult(
            success=True,
            outcome="navigated",
            before_url=before_url,
            after_url=page.url,
        )

    monkeypatch.setattr(session, "execute", execute)
    toolset = BrowserToolset(session, task, tab_id, emit)
    result = json.loads(await toolset.navigate("https://www.bing.com/"))

    assert result["result"]["success"] is search_enabled
    assert bool(executed) is search_enabled
    assert task.model_dump(include={"seed_urls", "inferred_seeds"}) == original_seeds
    assert toolset._initial_domains == [domain]
    assert not toolset.is_quarantined
    action_trace = next(trace for trace in traces if trace.event == "action")
    if search_enabled:
        assert "bing.com" in toolset.fallback_search_domains
        assert action_trace.metadata["search_fallback_used"] is True
        assert "bing.com" in action_trace.metadata["fallback_search_domains"]
        denied = json.loads(await toolset.navigate("https://unrelated.com/"))
        assert denied["result"]["success"] is False
        assert len(executed) == 1
    else:
        assert toolset.fallback_search_domains == []
        assert task.allowed_domains == [domain]


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
    session._register_page(page1, "tab-1")

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
    assert session._owned_pages[listing_tab_id].front_count == 1
    assert session._owned_pages[search_tab_id].front_count == 1

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


@pytest.mark.asyncio
async def test_persistent_session_reuses_initial_tab_and_releases_profile_lock(
    tmp_path, monkeypatch
):
    profile_dir = tmp_path / "persistent-profile"
    launched_kwargs: dict[str, object] = {}

    class _InitialBlankPage(_FakePageWithPopup):
        def __init__(self) -> None:
            super().__init__()
            self.url = "about:blank"
            self.goto_calls: list[str] = []

        async def goto(self, url: str, **kwargs: object) -> None:
            self.goto_calls.append(url)
            self.url = url

    initial_page = _InitialBlankPage()

    class _FakePersistentContext:
        def __init__(self) -> None:
            self.pages = [initial_page]
            self.new_page_calls = 0
            self.closed = False
            self.init_scripts: list[str] = []

        async def new_page(self) -> _InitialBlankPage:
            self.new_page_calls += 1
            return _InitialBlankPage()

        async def add_init_script(self, script: str) -> None:
            self.init_scripts.append(script)

        async def close(self) -> None:
            self.closed = True

    persistent_context = _FakePersistentContext()

    class _FakeChromium:
        async def launch_persistent_context(self, user_data_dir: str, **kwargs: object):
            launched_kwargs["user_data_dir"] = user_data_dir
            launched_kwargs["kwargs"] = kwargs
            return persistent_context

    class _FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = _FakeChromium()
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    pw_instance = _FakePlaywrightInstance()

    class _FakePlaywrightFactory:
        async def start(self) -> _FakePlaywrightInstance:
            return pw_instance

    monkeypatch.setattr(
        browse_session,
        "_get_async_playwright",
        lambda cfg: (_FakePlaywrightFactory, True),
    )

    cfg = GhostConfig.from_kwargs(
        {"headless": False, "user_data_dir": str(profile_dir)}
    )
    async with GhostBrowserSession(cfg) as session:
        # While active, a second session cannot share the same profile directory.
        with pytest.raises(RuntimeError, match="already in use"):
            async with GhostBrowserSession(cfg):
                pass
        first_tab = await session.open_page("https://example.com/start")
        second_tab = await session.open_page("https://example.com/second")
        assert first_tab.url == "https://example.com/start"
        assert second_tab.url == "https://example.com/second"
        assert initial_page.goto_calls == ["https://example.com/start"]
        assert persistent_context.new_page_calls == 1

    assert launched_kwargs["kwargs"] == {
        "headless": False,
        "chromium_sandbox": True,
        "no_viewport": True,
        "channel": "chrome",
        "args": ["--mute-audio"],
    }
    assert persistent_context.init_scripts == []
    assert persistent_context.closed is True
    assert pw_instance.stopped is True

    # Lock is released after teardown so a subsequent run can reuse the profile.
    lock = browse_session.acquire_profile_lock(profile_dir)
    lock.release()


def test_element_geometry_accepts_long_page_dimensions():
    element = ElementRef(
        ref="e1",
        snapshot_id="snapshot-1",
        tab_id="tab-1",
        frame_id="main",
        node_id="0:1",
        bbox_y=45_000.5,
        bbox_width=1_200,
        bbox_height=23_145.9921875,
    )

    assert element.bbox_height == 23_145.9921875
