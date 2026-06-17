"""
Tests for ghost browsing (stealth/agentic URL parsing).

These tests double as usage documentation for the `ghost` feature:

- Enable ghost browsing per-call:           parse(url, ghost=True)
- Tune it with a dict:                       parse(url, ghost={"wait_until": "networkidle",
                                                               "auto_scroll": True,
                                                               "headless": False})
- Attach to a running browser over CDP:      set LEXOID_CDP_URL=http://localhost:9222
                                             (or ghost={"cdp_url": "http://localhost:9222"})
- Persistent profile (cookies/login):        set LEXOID_GHOST_PROFILE_DIR=/path/to/profile
- Agentic navigation before extraction:      parse(url, ghost={"navigate": True,
                                                               "nav_instruction": "open pricing",
                                                               "nav_model": "gpt-4o"})

The unit tests need no network, browser, or API key. The integration tests
(stealth, acquisition modes, CDP attach, agentic navigation) use real network,
the Playwright Chromium binary, and API keys — like the existing
`test_dynamic_js_parsing`.
"""

import asyncio
import os
import subprocess
import tempfile
import time
import urllib.request

import pytest
from dotenv import load_dotenv

from lexoid.core import ghost, utils
from lexoid.core.ghost import (
    GhostConfig,
    _format_element,
    _normalize_step_usage,
    _parse_action,
    ghost_get_html,
)

load_dotenv()

# A reachable, JS-rendered test site (mirrors the external-URL style of the
# existing test_parser.py suite).
TEST_URL = "https://quotes.toscrape.com/"
TEST_URL_JS = "https://quotes.toscrape.com/js/"

GHOST_ENV_VARS = [
    "LEXOID_CDP_URL",
    "LEXOID_GHOST",
    "LEXOID_GHOST_PROFILE_DIR",
]


def _chromium_executable():
    """Path to the Playwright-managed Chromium, or None if unavailable."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        return None


def _has_google_key():
    return bool(os.getenv("GOOGLE_API_KEY"))


async def _acquire_and_probe(opts, url=TEST_URL):
    """Drive ghost's acquisition + a navigator.webdriver probe; return (mode, webdriver)."""
    cfg = GhostConfig.from_kwargs(opts)
    async_playwright, patchright_active = ghost._get_async_playwright(cfg)
    if cfg.cdp_url:
        patchright_active = True
    async with async_playwright() as p:
        async with ghost.acquire_page(p, cfg, patchright_active) as (page, mode):
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            webdriver = await page.evaluate("navigator.webdriver")
            return mode, webdriver


@pytest.fixture(autouse=True)
def _clear_ghost_env(monkeypatch):
    """Ensure ghost env vars don't leak between tests."""
    for var in GHOST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------- #
# GhostConfig resolution — how the `ghost` option is interpreted
# --------------------------------------------------------------------------- #


def test_ghost_disabled_by_default():
    # No `ghost` kwarg and no env vars -> ghost browsing stays off (legacy path).
    assert GhostConfig.from_kwargs(None).enabled is False
    assert GhostConfig.from_kwargs(False).enabled is False
    assert GhostConfig.from_kwargs({}).enabled is False


def test_ghost_enable_via_bool_uses_sane_defaults():
    cfg = GhostConfig.from_kwargs(True)
    assert cfg.enabled is True
    assert cfg.stealth is True
    assert cfg.headless is True
    assert cfg.wait_until == "networkidle"
    assert cfg.auto_scroll is True
    assert cfg.navigate is False  # agentic loop is opt-in within ghost
    assert cfg.cdp_url is None


def test_ghost_dict_overrides_fields():
    cfg = GhostConfig.from_kwargs(
        {
            "wait_until": "load",
            "headless": False,
            "auto_scroll": False,
            "timeout_ms": 5000,
            "navigate": True,
            "nav_instruction": "open the pricing tab",
            "nav_model": "gpt-4o",
            "nav_max_steps": 3,
        }
    )
    assert cfg.enabled is True
    assert cfg.wait_until == "load"
    assert cfg.headless is False
    assert cfg.auto_scroll is False
    assert cfg.timeout_ms == 5000
    assert cfg.navigate is True
    assert cfg.nav_instruction == "open the pricing tab"
    assert cfg.nav_model == "gpt-4o"
    assert cfg.nav_max_steps == 3


def test_ghost_cdp_via_env_enables_attach_mode(monkeypatch):
    # Setting the CDP endpoint alone is enough to enable ghost (CDP attach mode).
    monkeypatch.setenv("LEXOID_CDP_URL", "http://localhost:9222")
    cfg = GhostConfig.from_kwargs(None)
    assert cfg.enabled is True
    assert cfg.cdp_url == "http://localhost:9222"


def test_ghost_flag_and_profile_via_env(monkeypatch):
    monkeypatch.setenv("LEXOID_GHOST", "1")
    monkeypatch.setenv("LEXOID_GHOST_PROFILE_DIR", "/tmp/ghost-profile")
    cfg = GhostConfig.from_kwargs(None)
    assert cfg.enabled is True
    assert cfg.user_data_dir == "/tmp/ghost-profile"


def test_dict_cdp_url_overrides_env(monkeypatch):
    monkeypatch.setenv("LEXOID_CDP_URL", "http://env:9222")
    cfg = GhostConfig.from_kwargs({"cdp_url": "http://explicit:9999"})
    assert cfg.cdp_url == "http://explicit:9999"


def test_set_of_marks_enabled_by_default():
    # Set-of-marks (numbered element boxes on the screenshot) is on by default
    # for the agentic loop, and can be turned off.
    assert GhostConfig.from_kwargs(True).set_of_marks is True
    assert GhostConfig.from_kwargs({"set_of_marks": False}).set_of_marks is False


def test_format_element_marks_role_and_offscreen():
    on = _format_element(0, {"tag": "button", "role": "", "text": "Buy", "in_viewport": True})
    assert on == "[0] <button> Buy"
    off = _format_element(
        3, {"tag": "a", "role": "link", "text": "Next", "in_viewport": False}
    )
    assert off == "[3] <a role=link> (off-screen) Next"


def test_for_child_disables_agentic_navigation():
    # During recursive crawls, only the root URL runs the (costly) agentic loop.
    cfg = GhostConfig.from_kwargs(
        {"navigate": True, "nav_instruction": "x", "wait_until": "load"}
    )
    child = cfg.for_child()
    assert child.navigate is False
    assert child.nav_instruction is None
    # Other settings are preserved for children.
    assert child.wait_until == "load"
    assert child.enabled is True


# --------------------------------------------------------------------------- #
# Agentic action parsing — the LLM's per-step JSON action
# --------------------------------------------------------------------------- #


def test_parse_action_plain_json():
    action = _parse_action('{"action": "click", "index": 2, "reason": "open menu"}')
    assert action == {"action": "click", "index": 2, "reason": "open menu"}


def test_parse_action_code_fenced():
    raw = '```json\n{"action": "done", "reason": "content visible"}\n```'
    assert _parse_action(raw) == {"action": "done", "reason": "content visible"}


def test_parse_action_with_surrounding_prose():
    raw = 'Sure! Here is the next step:\n{"action": "scroll", "reason": "load more"} Done.'
    assert _parse_action(raw) == {"action": "scroll", "reason": "load more"}


def test_parse_action_garbage_returns_none():
    assert _parse_action("not json at all") is None
    assert _parse_action("") is None


# --------------------------------------------------------------------------- #
# Token usage threading — agentic usage surfaces in the result dict
# --------------------------------------------------------------------------- #


def test_token_usage_threaded_into_result(monkeypatch):
    """When the agentic loop runs, its LLM token usage appears in the result."""
    fake_html = "<html><head><title>T</title></head><body><h1>Hi</h1></body></html>"
    fake_usage = {"input": 120, "output": 30, "total": 150}
    monkeypatch.setattr(ghost, "ghost_get_html", lambda url, cfg: (fake_html, fake_usage))

    content = utils.read_html_content("https://example.com", ghost_opts=True)
    assert content["token_usage"] == fake_usage


def test_no_token_usage_key_when_navigation_did_not_run(monkeypatch):
    """A plain ghost fetch (no agentic loop) adds no token_usage key."""
    fake_html = "<html><head><title>T</title></head><body><h1>Hi</h1></body></html>"
    zero_usage = {"input": 0, "output": 0, "total": 0}
    monkeypatch.setattr(ghost, "ghost_get_html", lambda url, cfg: (fake_html, zero_usage))

    content = utils.read_html_content("https://example.com", ghost_opts=True)
    assert "token_usage" not in content


def test_disabled_ghost_returns_none_html():
    html, usage = ghost.ghost_get_html("https://example.com", GhostConfig(enabled=False))
    assert html is None
    assert usage == {"input": 0, "output": 0, "total": 0}


# --------------------------------------------------------------------------- #
# Agentic navigation loop — accumulates usage across steps (mocked LLM + page)
# --------------------------------------------------------------------------- #


class _FakeKeyboard:
    def __init__(self, press_sink, type_sink):
        self._press = press_sink
        self._type = type_sink

    async def press(self, key):
        self._press.append(key)

    async def type(self, text, delay=0):
        self._type.append(text)


class _FakePage:
    """Minimal async stand-in for a Playwright Page used by the agentic loop.

    `input_type` controls the collected element's input type (use "password" to
    exercise the credential guard). `progressing=True` makes the page state
    change each step so the no-progress detector doesn't stop the loop early.
    """

    def __init__(self, input_type="", progressing=False, el_tag=None):
        self.url = "https://example.com"
        self.input_type = input_type
        self.el_tag = el_tag
        self.progressing = progressing
        self._tick = 0
        self.clicked = []
        self.filled = []
        self.typed = []
        self.selected = []
        self.hovered = []
        self.pressed = []
        self.went_back = 0
        self.reloaded = 0
        self.keyboard = _FakeKeyboard(self.pressed, self.typed)

    async def evaluate(self, js, *args):
        # The element-collector JS contains getBoundingClientRect and returns the
        # element list; the combobox option-finder JS queries [role=option] and
        # returns a selector; set-of-marks / scroll JS return nothing.
        if "getBoundingClientRect" in js:
            return [
                {
                    "tag": self.el_tag or ("input" if self.input_type else "button"),
                    "role": "",
                    "input_type": self.input_type,
                    "text": "Pricing",
                    "selector": "#pricing",
                    "in_viewport": True,
                }
            ]
        if "role=option" in js:
            return "#opt0"
        return None

    async def screenshot(self):
        return b"\x89PNG fake"

    async def title(self):
        if self.progressing:
            self._tick += 1
            return f"Example {self._tick}"
        return "Example"

    async def click(self, selector, timeout=None):
        self.clicked.append(selector)

    async def fill(self, selector, text):
        self.filled.append((selector, text))

    async def select_option(self, selector, label=None, value=None):
        self.selected.append((selector, label if label is not None else value))

    async def hover(self, selector, timeout=None):
        self.hovered.append(selector)

    async def go_back(self, timeout=None):
        self.went_back += 1

    async def reload(self, timeout=None):
        self.reloaded += 1

    async def focus(self, selector, timeout=None):
        pass

    async def goto(self, url, **kwargs):
        self.url = url

    async def wait_for_load_state(self, state, timeout=None):
        pass


def test_agentic_loop_accumulates_usage_and_executes_actions(monkeypatch):
    """The loop should sum per-step usage and stop on a `done` action."""
    calls = {"n": 0}

    def fake_create_response(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            response = '{"action": "click", "index": 0, "reason": "open pricing"}'
        else:
            response = '{"action": "done", "reason": "pricing visible"}'
        return {
            "response": response,
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        }

    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response", fake_create_response
    )

    cfg = GhostConfig(
        enabled=True,
        navigate=True,
        nav_instruction="open the pricing tab",
        nav_max_steps=5,
    )
    page = _FakePage()
    usage, _final_page = asyncio.run(ghost._run_agentic_navigation(page, cfg))

    # Two LLM calls (click, then done); usage is summed and normalized.
    assert calls["n"] == 2
    assert usage == {"input": 200, "output": 40, "total": 240}
    # The "click" action was executed against the element's selector.
    assert page.clicked == ["#pricing"]


def test_normalize_step_usage_accepts_both_provider_shapes():
    # Gemini-style keys.
    assert _normalize_step_usage({"input": 10, "output": 4, "total": 14}) == {
        "input": 10,
        "output": 4,
        "total": 14,
    }
    # OpenAI/Anthropic-style keys.
    assert _normalize_step_usage(
        {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    ) == {"input": 10, "output": 4, "total": 14}
    # Missing total is derived from input + output.
    assert _normalize_step_usage({"input_tokens": 10, "output_tokens": 4}) == {
        "input": 10,
        "output": 4,
        "total": 14,
    }
    assert _normalize_step_usage(None) == {"input": 0, "output": 0, "total": 0}


def _scripted_create_response(calls, responses):
    """Return a fake create_response that emits `responses` in order."""

    def fake(**kwargs):
        resp = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return {
            "response": resp,
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }

    return fake


def test_agentic_loop_executes_rich_actions(monkeypatch):
    """keypress / hover / back / refresh all dispatch to the page."""
    calls = {"n": 0}
    responses = [
        '{"action": "keypress", "keys": "Enter"}',
        '{"action": "hover", "index": 0}',
        '{"action": "back"}',
        '{"action": "refresh"}',
        '{"action": "done"}',
    ]
    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response",
        _scripted_create_response(calls, responses),
    )
    cfg = GhostConfig(
        enabled=True, navigate=True, nav_instruction="x", nav_max_steps=6
    )
    page = _FakePage(progressing=True)  # avoid the no-progress early stop
    asyncio.run(ghost._run_agentic_navigation(page, cfg))

    assert page.pressed == ["Enter"]
    assert page.hovered == ["#pricing"]
    assert page.went_back == 1
    assert page.reloaded == 1


def test_select_native_dropdown(monkeypatch):
    """`select` on a native <select> uses Playwright select_option."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response",
        _scripted_create_response(
            calls,
            ['{"action": "select", "index": 0, "text": "opt"}', '{"action": "done"}'],
        ),
    )
    cfg = GhostConfig(enabled=True, navigate=True, nav_instruction="x", nav_max_steps=3)
    page = _FakePage(el_tag="select", progressing=True)
    asyncio.run(ghost._run_agentic_navigation(page, cfg))
    assert page.selected == [("#pricing", "opt")]


def test_select_combobox_opens_filters_and_clicks_option(monkeypatch):
    """`select` on a non-native dropdown opens it, types to filter, clicks the option."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response",
        _scripted_create_response(
            calls,
            [
                '{"action": "select", "index": 0, "text": "Unknown"}',
                '{"action": "done"}',
            ],
        ),
    )
    cfg = GhostConfig(enabled=True, navigate=True, nav_instruction="x", nav_max_steps=3)
    page = _FakePage(progressing=True)  # button tag -> combobox path
    asyncio.run(ghost._run_agentic_navigation(page, cfg))

    # Opened the combobox, typed the filter, then clicked the matched option.
    assert page.clicked == ["#pricing", "#opt0"]
    assert page.typed == ["Unknown"]
    assert page.selected == []  # native select_option NOT used for a combobox


def test_agentic_loop_blocks_typing_into_password_field(monkeypatch):
    """The credential guard refuses to fill password inputs."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response",
        _scripted_create_response(
            calls,
            ['{"action": "type", "index": 0, "text": "secret"}', '{"action": "done"}'],
        ),
    )
    cfg = GhostConfig(
        enabled=True, navigate=True, nav_instruction="x", nav_max_steps=3
    )
    page = _FakePage(input_type="password", progressing=True)
    asyncio.run(ghost._run_agentic_navigation(page, cfg))

    assert page.typed == []  # never typed the credential
    assert page.pressed == []  # never submitted


def test_agentic_loop_types_without_submitting(monkeypatch):
    """`type` focuses + keys the text (React/segmented-friendly) and does NOT submit."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response",
        _scripted_create_response(
            calls,
            ['{"action": "type", "index": 0, "text": "213584631"}', '{"action": "done"}'],
        ),
    )
    cfg = GhostConfig(
        enabled=True, navigate=True, nav_instruction="x", nav_max_steps=3
    )
    page = _FakePage(input_type="text", progressing=True)
    asyncio.run(ghost._run_agentic_navigation(page, cfg))

    assert page.clicked == ["#pricing"]  # focused first
    assert page.typed == ["213584631"]
    assert page.pressed == []  # no auto-submit


def test_agentic_loop_stops_on_no_progress(monkeypatch):
    """Loop detection stops well before nav_max_steps when nothing changes."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "lexoid.core.parse_type.llm_parser.create_response",
        _scripted_create_response(
            calls, ['{"action": "scroll", "direction": "down"}']
        ),
    )
    cfg = GhostConfig(
        enabled=True, navigate=True, nav_instruction="x", nav_max_steps=10
    )
    page = _FakePage()  # static state -> sig never changes
    asyncio.run(ghost._run_agentic_navigation(page, cfg))
    assert calls["n"] <= 3  # stalled out, didn't run all 10 steps


def test_same_site_compares_registrable_domain():
    from lexoid.core.ghost import _same_site

    assert _same_site("https://quotes.toscrape.com/page/2/", "https://quotes.toscrape.com/")
    assert _same_site("https://www.example.com/a", "https://api.example.com/b")
    assert not _same_site("https://example.com", "https://evil.com")


def test_downscale_png_shrinks_oversized_screenshot():
    from io import BytesIO

    from PIL import Image

    from lexoid.core.ghost import _downscale_png

    buf = BytesIO()
    Image.new("RGB", (2000, 1000), "white").save(buf, format="PNG")
    big = buf.getvalue()

    small = _downscale_png(big, 1280)
    assert max(Image.open(BytesIO(small)).size) == 1280
    # Already within bounds -> returned unchanged.
    assert _downscale_png(big, 4000) == big


def test_new_agentic_config_defaults_and_overrides():
    cfg = GhostConfig.from_kwargs(True)
    assert cfg.screenshot_max_dim == 1280
    assert cfg.nav_history_steps == 5
    assert cfg.nav_same_domain is True
    cfg2 = GhostConfig.from_kwargs(
        {"screenshot_max_dim": 800, "nav_history_steps": 3, "nav_same_domain": False}
    )
    assert cfg2.screenshot_max_dim == 800
    assert cfg2.nav_history_steps == 3
    assert cfg2.nav_same_domain is False


# --------------------------------------------------------------------------- #
# Integration tests (real network / browser / API keys — the real use case).
# These mirror the external-URL style already used in test_parser.py.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ghost_js_rendering_end_to_end():
    """
    Reliable JS rendering: ghost browsing executes client-side JS so
    dynamically-injected content is captured. "Albert Einstein" only appears
    after the page's JS runs (plain requests.get would miss it).
    """
    from lexoid.api import parse

    result = parse(
        TEST_URL_JS,
        parser_type="STATIC_PARSE",
        ghost={"auto_scroll": True, "timeout_ms": 25000},
    )
    assert "Einstein" in result["raw"]


@pytest.mark.asyncio
async def test_stealth_hides_webdriver_flag():
    """
    Bot-detection bypass: with stealth on, navigator.webdriver is hidden;
    with stealth off it is exposed (the signal headless automation leaks).
    """
    mode, webdriver_on = await _acquire_and_probe({"headless": True})
    assert mode == "fresh"
    assert webdriver_on is None  # hidden by the stealth init script

    _mode, webdriver_off = await _acquire_and_probe(
        {"headless": True, "stealth": False}
    )
    assert webdriver_off is True  # plain automation leaks navigator.webdriver


@pytest.mark.asyncio
async def test_fresh_mode_is_default_acquisition():
    mode, _ = await _acquire_and_probe(True)
    assert mode == "fresh"


@pytest.mark.asyncio
async def test_persistent_profile_mode_persists_data():
    """A persistent profile dir is created/populated and reused across runs."""
    profile_dir = tempfile.mkdtemp(prefix="lexoid-ghost-")
    mode, _ = await _acquire_and_probe(
        {"headless": True, "user_data_dir": profile_dir}
    )
    assert mode == "persistent"
    assert len(os.listdir(profile_dir)) > 0  # Chromium wrote the profile


@pytest.mark.asyncio
async def test_set_of_marks_overlay_drawn_then_removed():
    """
    Set-of-marks: a screenshot is produced with numbered boxes over interactive
    elements, and the overlay is removed afterward so it never leaks into the
    extracted HTML.
    """
    cfg = GhostConfig.from_kwargs({"headless": True})
    async_playwright, patchright_active = ghost._get_async_playwright(cfg)
    async with async_playwright() as p:
        async with ghost.acquire_page(p, cfg, patchright_active) as (page, _mode):
            await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=25000)
            elements = await ghost._collect_elements(page)
            assert elements, "expected interactive elements on the page"
            assert any(e.get("in_viewport") for e in elements)

            png = await ghost._screenshot_with_marks(page, elements, cfg)
            assert png  # non-empty screenshot bytes

            # The overlay must be gone after the screenshot is taken.
            leaked = await page.evaluate(
                "() => !!document.getElementById('lexoid-som')"
            )
            assert leaked is False


def test_cdp_attach_reuses_running_browser_and_leaves_it_alive():
    """
    Truest "ghost": attach over CDP to a separately-launched browser, parse a
    page, and leave that browser running (we only close the tab we opened).

    Kept synchronous so the Playwright sync API (used to locate the Chromium
    executable) does not run inside an active asyncio loop.
    """
    exe = _chromium_executable()
    if not exe:
        pytest.skip("Playwright Chromium executable not available")

    port = 9242
    profile_dir = tempfile.mkdtemp(prefix="lexoid-cdp-")
    proc = subprocess.Popen(
        [
            exe,
            "--headless=new",
            "--no-sandbox",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        endpoint = f"http://localhost:{port}"
        up = False
        for _ in range(40):
            try:
                urllib.request.urlopen(f"{endpoint}/json/version", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        assert up, "CDP endpoint did not come up"

        cfg = GhostConfig.from_kwargs(
            {"cdp_url": endpoint, "timeout_ms": 25000, "auto_scroll": False}
        )
        html, usage = ghost_get_html(TEST_URL, cfg)
        assert html is not None and "Einstein" in html
        # Attaching must NOT close the user's browser.
        assert proc.poll() is None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


@pytest.mark.asyncio
async def test_dead_cdp_endpoint_falls_back_gracefully():
    """A dead CDP endpoint yields None so the caller falls back to legacy fetch."""
    from lexoid.api import parse

    # Port 9 is the discard service — connect_over_cdp will fail fast.
    result = parse(
        TEST_URL,
        parser_type="STATIC_PARSE",
        ghost={"cdp_url": "http://localhost:9", "timeout_ms": 15000},
    )
    # Legacy path still returns the page content.
    assert "Einstein" in result["raw"]


@pytest.mark.asyncio
async def test_agentic_navigation_real_llm_reports_token_usage():
    """
    Agentic navigation with a real LLM: the loop drives the page toward an
    instruction and the LLM token usage is surfaced in the result's
    token_usage. (Navigation outcome is non-deterministic; we assert the loop
    ran and reported real cost, plus that content was extracted.)
    """
    if not _has_google_key():
        pytest.skip("GOOGLE_API_KEY not set")

    from lexoid.api import parse

    result = parse(
        TEST_URL_JS,
        parser_type="STATIC_PARSE",
        ghost={
            "timeout_ms": 25000,
            "auto_scroll": False,
            "navigate": True,
            "nav_instruction": "Click the 'Next' button to go to the next page of quotes, then stop.",
            "nav_max_steps": 4,
        },
    )
    assert result["raw"].strip()
    assert "token_usage" in result
    assert result["token_usage"]["total"] > 0
    assert result["token_usage"]["input"] > 0
