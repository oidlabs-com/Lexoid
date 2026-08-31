"""Async Playwright session with strict Lexoid tab ownership."""

from __future__ import annotations

import hashlib
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

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

    async def snapshot(self, tab_id: str) -> BrowserSnapshot:
        """Create a compact accessibility-oriented observation for one owned tab."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        entries = await page.locator(
            "button, a, input, select, textarea, [role]"
        ).evaluate_all(
            """elements => elements.slice(0, 100).map((element, index) => ({
                index,
                role: element.getAttribute('role') || element.tagName.toLowerCase(),
                name: element.getAttribute('aria-label') || element.innerText || element.value || '',
                tag: element.tagName.toLowerCase()
            }))"""
        )
        revision = self._revisions[tab_id]
        snapshot_id = f"snapshot-{uuid4().hex}"
        refs = [
            ElementRef(
                ref=f"e{entry['index']}",
                snapshot_id=snapshot_id,
                tab_id=tab_id,
                frame_id="main",
                node_id=f"{revision}:{entry['index']}",
                role=entry["role"],
                name=str(entry["name"])[:1000],
                tag=entry["tag"],
                ordinal=entry["index"],
            )
            for entry in entries
        ]
        digest = hashlib.sha256(repr(entries).encode("utf-8")).hexdigest()
        snapshot = BrowserSnapshot(
            snapshot_id=snapshot_id,
            tab_id=tab_id,
            page_revision=revision,
            url=page.url,
            title=await page.title(),
            elements=refs,
            content_hash=digest,
        )
        self._snapshots[snapshot_id] = snapshot
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
            selector = "button, a, input, select, textarea, [role]"
            locator = page.locator(selector).nth(element.ordinal or 0)
            if action.kind == "click":
                await locator.click(timeout=self._config.timeout_ms)
            elif action.kind == "type":
                await locator.fill(action.text or "", timeout=self._config.timeout_ms)
            elif action.kind == "select":
                try:
                    await locator.select_option(label=action.text or "")
                except Exception:
                    await locator.click(timeout=self._config.timeout_ms)
                    option = page.get_by_role("option", name=action.text or "").first
                    await option.click(timeout=self._config.timeout_ms)
            elif action.kind == "keypress":
                await page.keyboard.press(action.text or "Enter")
            elif action.kind == "hover":
                await locator.hover(timeout=self._config.timeout_ms)
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
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=2_000)
        except Exception:
            pass
        await page.wait_for_timeout(300)
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
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=2_000)
                except Exception:
                    pass
                await page.wait_for_timeout(500)
                self._revisions[tab_id] += 1
                return True
        return False
