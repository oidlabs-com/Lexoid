"""Async Playwright session with strict Lexoid tab ownership."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import uuid4

from loguru import logger

from lexoid.core.browse.schemas import (
    BrowserAction,
    BrowserActionResult,
    BrowserSnapshot,
    ElementRef,
    OpenTab,
)
from lexoid.core.ghost import GhostConfig, _get_async_playwright


class TabGoneError(RuntimeError):
    """Raised when an action targets a closed Lexoid-owned tab."""


_DOM_QUIET_JS = """
(idleMs) => new Promise((resolve) => {
    let timer;
    const observer = new MutationObserver(() => {
        clearTimeout(timer);
        timer = setTimeout(() => { observer.disconnect(); resolve(true); }, idleMs);
    });
    observer.observe(document.documentElement, {
        childList: true, subtree: true, characterData: true, attributes: true
    });
    timer = setTimeout(() => { observer.disconnect(); resolve(true); }, idleMs);
});
"""

_FORM_STATE_JS = """
() => Array.from(document.querySelectorAll('input, textarea, select'))
    .filter(el => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
            && el.type !== 'password' && el.type !== 'hidden';
    })
    .map(el => (el.value || '').trim())
    .filter(value => value.length > 0)
    .slice(0, 50)
"""


class GhostBrowserSession(AbstractAsyncContextManager):
    """Own only pages opened by Lexoid during an async browser session."""

    def __init__(self, config: GhostConfig) -> None:
        self._config = config
        self._playwright = None
        self._browser = None
        self._context = None
        self._owned_pages: dict[str, object] = {}
        self._retained_tabs: set[str] = set()
        self._revisions: dict[str, int] = {}
        self._snapshots: dict[str, BrowserSnapshot] = {}
        self._snapshot_handles: dict[str, dict[str, Any]] = {}
        self._settle_idle_ms = 500
        self._settle_timeout_ms = min(config.timeout_ms, 15_000)

    async def __aenter__(self) -> "GhostBrowserSession":
        factory, _ = _get_async_playwright(self._config)
        self._playwright = await factory().start()
        if self._config.cdp_url:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._config.cdp_url
            )
            self._context = self._browser.contexts[0]
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=self._config.headless
            )
            self._context = await self._browser.new_context()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.cleanup()
        if self._browser is not None and not self._config.cdp_url:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def open_page(self, url: str) -> OpenTab:
        """Open and navigate a Lexoid-owned page without adopting user tabs."""
        page = await self._context.new_page()
        tab_id = f"tab-{uuid4().hex}"
        self._owned_pages[tab_id] = page
        self._revisions[tab_id] = 0
        await page.goto(
            url, wait_until="domcontentloaded", timeout=self._config.timeout_ms
        )
        return await self.tab(tab_id)

    async def tab(self, tab_id: str) -> OpenTab:
        """Return metadata for an active owned tab or raise ``TabGoneError``."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        target_id = getattr(page, "guid", tab_id)
        return OpenTab(
            tab_id=tab_id,
            target_id=str(target_id),
            url=page.url,
            title=await page.title(),
        )

    async def retain_page(self, tab_id: str) -> OpenTab:
        """Preserve one Lexoid-owned page after session cleanup."""
        tab = await self.tab(tab_id)
        self._retained_tabs.add(tab_id)
        return tab

    async def content(self, tab_id: str) -> str:
        """Return the current HTML for an owned tab."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        return await page.content()

    async def text_content(self, tab_id: str) -> str:
        """Return the rendered visible text for an owned tab."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        return await page.evaluate(
            "() => (document.body && document.body.innerText) || ''"
        )

    async def form_state(self, tab_id: str) -> list[str]:
        """Return visible non-credential field values, showing what was submitted."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        try:
            return await page.evaluate(_FORM_STATE_JS)
        except Exception:
            logger.debug("Browse form state read failed")
            return []

    async def settle(self, tab_id: str) -> None:
        """Wait for rendering to stop changing instead of sleeping a fixed time."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        await self._settle_page(page)

    async def _settle_page(self, page) -> None:
        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=self._settle_timeout_ms
            )
        except Exception:
            logger.debug("Browse settle: load state wait timed out")
        try:
            await asyncio.wait_for(
                page.evaluate(_DOM_QUIET_JS, self._settle_idle_ms),
                timeout=self._settle_timeout_ms / 1000,
            )
        except Exception:
            logger.debug("Browse settle: DOM quiescence wait timed out")

    async def snapshot(self, tab_id: str) -> BrowserSnapshot:
        """Create a compact accessibility-oriented observation for one owned tab."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        locator = page.locator("button, a, input, select, textarea, [role]")
        entries = await locator.evaluate_all(
            """elements => elements.map((element, index) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                const visible = rect.width > 0 && rect.height > 0 &&
                    style.display !== 'none' && style.visibility !== 'hidden' &&
                    style.visibility !== 'collapse' && Number(style.opacity) !== 0;
                return {
                    index,
                    role: element.getAttribute('role') || element.tagName.toLowerCase(),
                    name: element.getAttribute('aria-label') || element.innerText || element.value || '',
                    tag: element.tagName.toLowerCase(),
                    bbox_x: rect.x,
                    bbox_y: rect.y,
                    bbox_width: rect.width,
                    bbox_height: rect.height,
                    visible,
                    enabled: !element.matches(':disabled') && element.getAttribute('aria-disabled') !== 'true'
                };
            }).filter(entry => entry.visible).slice(0, 100)"""
        )
        revision = self._revisions[tab_id]
        snapshot_id = f"snapshot-{uuid4().hex}"
        refs = []
        handles: dict[str, Any] = {}
        for entry in entries:
            if (
                not entry["visible"]
                or entry["bbox_width"] <= 0
                or entry["bbox_height"] <= 0
            ):
                continue
            ref = f"e{entry['index']}"
            handle = await locator.nth(entry["index"]).element_handle()
            if handle is None:
                continue
            refs.append(
                ElementRef(
                    ref=ref,
                    snapshot_id=snapshot_id,
                    tab_id=tab_id,
                    frame_id="main",
                    node_id=f"{revision}:{entry['index']}",
                    role=entry["role"],
                    name=str(entry["name"])[:1000],
                    tag=entry["tag"],
                    ordinal=entry["index"],
                    bbox_x=entry["bbox_x"],
                    bbox_y=entry["bbox_y"],
                    bbox_width=entry["bbox_width"],
                    bbox_height=entry["bbox_height"],
                    visible=entry["visible"],
                    enabled=entry["enabled"],
                )
            )
            handles[ref] = handle
        digest = hashlib.sha256(repr(entries).encode("utf-8")).hexdigest()
        viewport = await page.evaluate(
            """() => ({
                width: window.innerWidth,
                height: window.innerHeight,
                scrollX: window.scrollX,
                scrollY: window.scrollY
            })"""
        )
        snapshot = BrowserSnapshot(
            snapshot_id=snapshot_id,
            tab_id=tab_id,
            page_revision=revision,
            url=page.url,
            title=await page.title(),
            viewport_width=viewport["width"],
            viewport_height=viewport["height"],
            scroll_x=viewport["scrollX"],
            scroll_y=viewport["scrollY"],
            elements=refs,
            content_hash=digest,
        )
        self._snapshots[snapshot_id] = snapshot
        self._snapshot_handles[snapshot_id] = handles
        return snapshot

    async def execute(self, action: BrowserAction) -> BrowserActionResult:
        """Execute one current-snapshot action against its exact owned tab."""
        if action.kind == "done":
            return BrowserActionResult(success=True, outcome="navigation complete")
        if action.snapshot_id is None:
            return BrowserActionResult(
                success=False, outcome="missing snapshot reference"
            )
        snapshot = self._snapshots.get(action.snapshot_id)
        if snapshot is None or snapshot.page_revision != self._revisions.get(
            snapshot.tab_id
        ):
            return BrowserActionResult(
                success=False, outcome="stale reference", error_code="stale_ref"
            )
        page = self._owned_pages.get(snapshot.tab_id)
        if page is None or page.is_closed():
            return BrowserActionResult(
                success=False, outcome="tab closed", error_code="tab_gone"
            )
        before_url = page.url
        try:
            if action.kind in {"click", "type", "select", "hover"} and not action.ref:
                return BrowserActionResult(
                    success=False, outcome="missing element reference"
                )
            element = next(
                (item for item in snapshot.elements if item.ref == action.ref), None
            )
            if action.ref is not None and element is None:
                return BrowserActionResult(
                    success=False, outcome="stale reference", error_code="stale_ref"
                )
            handle = None
            if action.kind in {"click", "type", "select", "hover"}:
                handle = self._snapshot_handles.get(snapshot.snapshot_id, {}).get(
                    action.ref or ""
                )
                if handle is None:
                    return BrowserActionResult(
                        success=False,
                        outcome="stale reference",
                        error_code="stale_ref",
                    )
                if not await handle.is_visible() or not await handle.is_enabled():
                    return BrowserActionResult(
                        success=False,
                        outcome="stale reference",
                        error_code="stale_ref",
                    )
            if action.kind == "click":
                assert handle is not None
                await handle.click(timeout=self._config.timeout_ms)
            elif action.kind == "type":
                assert handle is not None
                await handle.fill(action.text or "", timeout=self._config.timeout_ms)
            elif action.kind == "select":
                assert handle is not None
                try:
                    await handle.select_option(label=action.text or "")
                except Exception:
                    await handle.click(timeout=self._config.timeout_ms)
                    option = page.get_by_role("option", name=action.text or "").first
                    await option.click(timeout=self._config.timeout_ms)
            elif action.kind == "keypress":
                await page.keyboard.press(action.text or "Enter")
            elif action.kind == "hover":
                assert handle is not None
                await handle.hover(timeout=self._config.timeout_ms)
            elif action.kind == "scroll":
                direction = -1 if action.text == "up" else 1
                await page.evaluate(
                    "direction => window.scrollBy(0, direction * window.innerHeight)",
                    direction,
                )
            elif action.kind == "navigate":
                await page.goto(
                    action.url or "",
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
            elif action.kind == "back":
                await page.go_back(timeout=self._config.timeout_ms)
            elif action.kind == "refresh":
                await page.reload(timeout=self._config.timeout_ms)
            elif action.kind == "wait":
                if action.text:
                    await page.get_by_text(action.text, exact=False).first.wait_for(
                        state="visible", timeout=self._config.timeout_ms
                    )
                else:
                    await page.wait_for_timeout(500)
            else:
                return BrowserActionResult(success=False, outcome="unsupported action")
        except Exception as error:
            return BrowserActionResult(success=False, outcome=str(error)[:1000])
        await self._settle_page(page)
        self._revisions[snapshot.tab_id] += 1
        return BrowserActionResult(
            success=True,
            outcome="action executed",
            before_url=before_url,
            after_url=page.url,
        )

    async def cleanup(self) -> None:
        """Close temporary Lexoid pages while preserving explicitly retained tabs."""
        for tab_id, page in list(self._owned_pages.items()):
            if tab_id not in self._retained_tabs and not page.is_closed():
                await page.close()

    async def advance_to_next_result_page(self, tab_id: str) -> bool:
        """Click a standard enabled next-page control, returning whether one existed."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        selectors = (
            "a[rel='next']",
            "button[aria-label*='next' i]",
            "a[aria-label*='next' i]",
            "button:has-text('Next')",
            "a:has-text('Next')",
        )
        for selector in selectors:
            locators = page.locator(selector)
            for index in range(await locators.count()):
                locator = locators.nth(index)
                if not await locator.is_visible():
                    continue
                if (
                    await locator.is_disabled()
                    or await locator.get_attribute("aria-disabled") == "true"
                ):
                    continue
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=5_000, force=True)
                await self._settle_page(page)
                self._revisions[tab_id] += 1
                return True
        return False
