"""Async Playwright session with strict Lexoid tab ownership."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import urlparse
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

_SNAPSHOT_ELEMENTS_JS = """
elements => {
    const modalSelectors = [
        'dialog[open]',
        '[role="dialog"]',
        '[role="alertdialog"]',
        '[aria-modal="true"]',
        '.csgp-modal:not([aria-hidden="true"])',
        '.modal.show',
        '.modal[style*="display: block"]'
    ].join(', ');

    const candidateModals = Array.from(document.querySelectorAll(modalSelectors)).filter(m => {
        const r = m.getBoundingClientRect();
        const s = window.getComputedStyle(m);
        return r.width > 0 && r.height > 0 &&
            s.display !== 'none' && s.visibility !== 'hidden' &&
            Number(s.opacity) !== 0 && m.getAttribute('aria-hidden') !== 'true';
    });

    let activeModal = null;
    if (candidateModals.length > 0) {
        activeModal = candidateModals.reduce((top, curr) => {
            if (!top) return curr;
            const topZ = parseInt(window.getComputedStyle(top).zIndex, 10) || 0;
            const currZ = parseInt(window.getComputedStyle(curr).zIndex, 10) || 0;
            return currZ >= topZ ? curr : top;
        }, null);
    }

    const isInsideModalOrPopup = (el) => {
        if (!activeModal) return false;
        if (activeModal.contains(el)) return true;
        const popup = el.closest('[role="listbox"], [role="menu"], [role="tooltip"], .cdk-overlay-container, [class*="dropdown-menu"], [class*="popup"]');
        if (popup) {
            const style = window.getComputedStyle(popup);
            const z = parseInt(style.zIndex, 10) || 0;
            const modalZ = parseInt(window.getComputedStyle(activeModal).zIndex, 10) || 0;
            return z >= modalZ;
        }
        return false;
    };

    const resolveName = (el) => {
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const parts = labelledBy.split(/\\s+/).map(id => {
                const node = document.getElementById(id);
                return node ? (node.innerText || node.textContent || '').trim() : '';
            }).filter(Boolean);
            if (parts.length > 0) return parts.join(' ');
        }

        if (el.id) {
            const escId = (window.CSS && window.CSS.escape) ? window.CSS.escape(el.id) : el.id.replace(/"/g, '\\\\"') ;
            const labelFor = document.querySelector(`label[for="${escId}"]`);
            if (labelFor && labelFor.innerText.trim()) return labelFor.innerText.trim();
        }

        const parentLabel = el.closest('label');
        if (parentLabel && parentLabel !== el) {
            const labelText = (parentLabel.innerText || '').trim();
            if (labelText) return labelText;
        }

        const placeholder = el.getAttribute('placeholder');
        if (placeholder && placeholder.trim()) return placeholder.trim();

        const title = el.getAttribute('title');
        if (title && title.trim()) return title.trim();

        return (el.innerText || el.value || '').trim();
    };

    const getFieldContext = (el) => {
        const fieldset = el.closest('fieldset');
        if (fieldset) {
            const legend = fieldset.querySelector('legend');
            if (legend && legend.innerText.trim()) return legend.innerText.trim().slice(0, 100);
        }
        const group = el.closest('[role="group"], [role="radiogroup"]');
        if (group) {
            const gl = group.getAttribute('aria-label') || (group.querySelector(':scope > [class*="label"], :scope > [class*="header"], :scope > [class*="title"]') || {}).innerText;
            if (gl && gl.trim()) return gl.trim().slice(0, 100);
        }
        let curr = el.parentElement;
        for (let i = 0; i < 3 && curr && curr !== document.body && (!activeModal || curr !== activeModal.parentElement); i++) {
            const heading = curr.querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6, :scope > label, :scope > [class*="header"], :scope > [class*="title"], :scope > [class*="label"]');
            if (heading && heading !== el && !heading.contains(el)) {
                const text = (heading.innerText || '').trim();
                if (text && text.length > 0 && text.length <= 100) return text;
            }
            curr = curr.parentElement;
        }
        return null;
    };

    return elements.map((element, index) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        const isVisible = rect.width > 0 && rect.height > 0 &&
            style.display !== 'none' && style.visibility !== 'hidden' &&
            style.visibility !== 'collapse' && Number(style.opacity) !== 0 &&
            element.getAttribute('aria-hidden') !== 'true' &&
            !element.hasAttribute('inert');

        const inModal = isInsideModalOrPopup(element);
        // Only treat an element as covered when another element is physically on top
        let covered = false;
        if (isVisible && activeModal && !inModal) {
            const cx = Math.min(Math.max(rect.x + rect.width / 2, 0), window.innerWidth - 1);
            const cy = Math.min(Math.max(rect.y + rect.height / 2, 0), window.innerHeight - 1);
            const topHit = document.elementFromPoint(cx, cy);
            covered = Boolean(topHit) && topHit !== element && !element.contains(topHit) && !topHit.contains(element);
        }
        const visible = isVisible && !covered;

        let checked = null;
        if (element.tagName.toLowerCase() === 'input' && (element.type === 'checkbox' || element.type === 'radio')) {
            checked = Boolean(element.checked);
        } else if (element.hasAttribute('aria-checked')) {
            checked = element.getAttribute('aria-checked') === 'true';
        }

        let selected = null;
        if (element.tagName.toLowerCase() === 'option') {
            selected = Boolean(element.selected);
        } else if (element.hasAttribute('aria-selected')) {
            selected = element.getAttribute('aria-selected') === 'true';
        }

        let expanded = null;
        if (element.hasAttribute('aria-expanded')) {
            expanded = element.getAttribute('aria-expanded') === 'true';
        }

        const inputType = element.tagName.toLowerCase() === 'input' ? (element.type || 'text') : null;
        const name = resolveName(element);
        const fieldContext = getFieldContext(element);

        return {
            index,
            role: element.getAttribute('role') || element.tagName.toLowerCase(),
            name,
            tag: element.tagName.toLowerCase(),
            bbox_x: rect.x,
            bbox_y: rect.y,
            bbox_width: rect.width,
            bbox_height: rect.height,
            visible,
            enabled: !element.matches(':disabled') && element.getAttribute('aria-disabled') !== 'true',
            checked,
            selected,
            expanded,
            input_type: inputType,
            field_context: fieldContext,
            in_modal: inModal,
        };
    }).filter(entry => entry.visible).slice(0, 100);
}
"""

_CONTAINER_SCROLL_JS = """
(element, dir) => {
    let curr = element;
    while (curr && curr !== document.body && curr !== document.documentElement) {
        const style = window.getComputedStyle(curr);
        const overflowY = style.overflowY || style.overflow;
        const isScrollable = (overflowY === 'auto' || overflowY === 'scroll') && curr.scrollHeight > curr.clientHeight;
        if (isScrollable) {
            curr.scrollBy({ top: dir * Math.max(curr.clientHeight * 0.8, 100), behavior: 'instant' });
            return;
        }
        curr = curr.parentElement;
    }
    element.scrollIntoView({ block: dir > 0 ? 'end' : 'start', behavior: 'instant' });
}
"""


def _normalize_tab_url(url: str) -> str:
    if not url or url.startswith("about:"):
        return ""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{scheme}://{netloc}{path}{query}{fragment}"


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
        self._pending_popups: list[tuple[str, str]] = []
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

    def _on_popup(self, opener_tab_id: str, popup_page: object) -> None:
        popup_tab_id = self._register_page(popup_page)
        self._pending_popups.append((opener_tab_id, popup_tab_id))

    def _register_page(self, page: object, tab_id: str | None = None) -> str:
        tid = tab_id or f"tab-{uuid4().hex}"
        self._owned_pages[tid] = page
        self._revisions[tid] = 0
        page.on("popup", lambda popup: self._on_popup(tid, popup))
        return tid

    async def open_page(self, url: str) -> OpenTab:
        """Open and navigate a Lexoid-owned page without adopting user tabs."""
        page = await self._context.new_page()
        tab_id = self._register_page(page)
        await page.goto(
            url, wait_until="domcontentloaded", timeout=self._config.timeout_ms
        )
        return await self.tab(tab_id)

    async def list_tabs(self) -> list[OpenTab]:
        """Return metadata for all active Lexoid-owned tabs."""
        tabs: list[OpenTab] = []
        for tab_id in list(self._owned_pages.keys()):
            try:
                tabs.append(await self.tab(tab_id))
            except (TabGoneError, Exception):
                continue
        return tabs

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
        entries = await locator.evaluate_all(_SNAPSHOT_ELEMENTS_JS)
        revision = self._revisions[tab_id]
        snapshot_id = f"snapshot-{uuid4().hex}"
        refs = []
        handles: dict[str, Any] = {}
        for entry in entries:
            if (
                not entry.get("visible", True)
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
                    role=entry.get("role"),
                    name=str(entry.get("name") or "")[:1000],
                    tag=entry.get("tag"),
                    ordinal=entry["index"],
                    bbox_x=entry["bbox_x"],
                    bbox_y=entry["bbox_y"],
                    bbox_width=entry["bbox_width"],
                    bbox_height=entry["bbox_height"],
                    visible=entry.get("visible", True),
                    enabled=entry.get("enabled", True),
                    checked=entry.get("checked"),
                    selected=entry.get("selected"),
                    expanded=entry.get("expanded"),
                    input_type=entry.get("input_type"),
                    field_context=entry.get("field_context"),
                    in_modal=bool(entry.get("in_modal", False)),
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
            if action.ref is not None:
                handle = self._snapshot_handles.get(snapshot.snapshot_id, {}).get(
                    action.ref
                )
                if action.kind in {"click", "type", "select", "hover"}:
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
                if action.ref and handle is not None:
                    await handle.evaluate(_CONTAINER_SCROLL_JS, direction)
                else:
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
        opened_tab_id: str | None = None
        opened_url: str | None = None
        reused_existing_tab = False
        matching_popups = [
            (opener, tid)
            for opener, tid in self._pending_popups
            if opener == snapshot.tab_id
        ]
        self._pending_popups = [
            (opener, tid)
            for opener, tid in self._pending_popups
            if opener != snapshot.tab_id
        ]
        for _, popup_tab_id in matching_popups:
            popup_page = self._owned_pages.get(popup_tab_id)
            if popup_page is None or popup_page.is_closed():
                continue
            await self._settle_page(popup_page)
            popup_url = popup_page.url
            norm_url = _normalize_tab_url(popup_url)
            existing_tab_id = None
            if norm_url:
                for owned_id, owned_page in self._owned_pages.items():
                    if (
                        owned_id != popup_tab_id
                        and not owned_page.is_closed()
                        and _normalize_tab_url(owned_page.url) == norm_url
                    ):
                        existing_tab_id = owned_id
                        break
            if existing_tab_id is not None:
                try:
                    await popup_page.close()
                    self._owned_pages.pop(popup_tab_id, None)
                    self._revisions.pop(popup_tab_id, None)
                    opened_tab_id = existing_tab_id
                    opened_url = self._owned_pages[existing_tab_id].url
                    reused_existing_tab = True
                except Exception:
                    logger.debug("Failed to close duplicate popup tab {}", popup_tab_id)
                    opened_tab_id = popup_tab_id
                    opened_url = popup_url
                    reused_existing_tab = False
            else:
                opened_tab_id = popup_tab_id
                opened_url = popup_url
                reused_existing_tab = False
        self._revisions[snapshot.tab_id] += 1
        return BrowserActionResult(
            success=True,
            outcome="action executed (reused existing tab)"
            if reused_existing_tab
            else "action executed",
            before_url=before_url,
            after_url=opened_url or page.url,
            target_bbox_x=element.bbox_x if element else None,
            target_bbox_y=element.bbox_y if element else None,
            target_bbox_width=element.bbox_width if element else None,
            target_bbox_height=element.bbox_height if element else None,
            opened_tab_id=opened_tab_id,
        )

    async def cleanup(self) -> None:
        """Close temporary pages while preserving explicitly retained tabs."""
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
