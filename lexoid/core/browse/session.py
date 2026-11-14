"""Async Playwright session with strict Lexoid tab ownership."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import AbstractAsyncContextManager
from typing import Any, Self
from urllib.parse import urlparse
from uuid import uuid4

from loguru import logger
from playwright.async_api import Error as PlaywrightError

from lexoid.core.browse.schemas import (
    BrowserAction,
    BrowserActionResult,
    BrowserSnapshot,
    ElementRef,
    MediaState,
    OpenTab,
)
from lexoid.core.ghost import (
    _STEALTH_INIT_SCRIPT,
    GhostConfig,
    ProfileDirectoryLock,
    _get_async_playwright,
    acquire_profile_lock,
    launch_browser_with_config,
    launch_persistent_context_with_config,
    resolve_no_viewport,
)

_SNAPSHOT_ATTEMPTS = 3

_MEDIA_STATE_JS = """
() => Array.from(document.querySelectorAll("video, audio"))
    .slice(0, 5)
    .map(element => ({
        media_type: element.tagName.toLowerCase(),
        paused: Boolean(element.paused),
        current_time: Number.isFinite(element.currentTime)
            ? Math.max(0, element.currentTime) : 0,
        duration: Number.isFinite(element.duration) && element.duration >= 0
            ? element.duration : null,
        ended: Boolean(element.ended),
        ready_state: element.readyState
    }))
"""
_SNAPSHOT_STATE_JS = f"""
() => {{
    const mediaState = ({_MEDIA_STATE_JS.strip()})();
    return {{
        width: window.innerWidth,
        height: window.innerHeight,
        scrollX: window.scrollX,
        scrollY: window.scrollY,
        media_state: mediaState
    }};
}}
"""


def _parse_media_state(values: Any) -> list[MediaState]:
    if not isinstance(values, list):
        raise TypeError("Media-state evaluation did not return a list")
    return [MediaState.model_validate(value) for value in values[:5]]


def _is_navigation_context_error(error: Exception) -> bool:
    message = str(error)
    return "Execution context was destroyed" in message or (
        "Cannot find context with specified id" in message
    )


class TabGoneError(RuntimeError):
    """Raised when an action targets a closed  tab."""


# Attribute churn (animations, carousels, ad slots) is ignored so dynamic pages can
# report quiet; the in-page max wait guarantees the observer always disconnects.
_DOM_QUIET_JS = """
({idleMs, maxMs}) => new Promise((resolve) => {
    let idleTimer;
    let done = false;
    const root = document.documentElement;
    const finish = (status) => {
        if (done) return;
        done = true;
        clearTimeout(idleTimer);
        clearTimeout(maxTimer);
        if (observer) observer.disconnect();
        resolve(status);
    };
    const observer = root ? new MutationObserver(() => {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => finish("quiet"), idleMs);
    }) : null;
    if (observer) {
        observer.observe(root, { childList: true, subtree: true, characterData: true });
    }
    idleTimer = setTimeout(() => finish("quiet"), idleMs);
    const maxTimer = setTimeout(() => finish("max_wait"), maxMs);
});
"""

_SETTLE_IDLE_MS = 500
_SETTLE_MAX_WAIT_MS = 4_000
_SETTLE_GRACE_S = 2.0

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
            href: element.closest('a[href]')?.href || null,
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
        self._profile_lock: ProfileDirectoryLock | None = None
        self._unclaimed_initial_page: Any = None
        self._effective_driver: str = "playwright"
        self._effective_mode: str = "fresh"
        self._effective_channel: str | None = None
        self._owned_pages: dict[str, object] = {}
        self._retained_tabs: set[str] = set()
        self._revisions: dict[str, int] = {}
        self._snapshots: dict[str, BrowserSnapshot] = {}
        self._snapshot_handles: dict[str, dict[str, Any]] = {}
        self._pending_popups: list[tuple[str, str]] = []
        self._settle_idle_ms = _SETTLE_IDLE_MS
        self._settle_timeout_ms = min(config.timeout_ms, 15_000)
        self._settle_max_wait_ms = min(config.timeout_ms, _SETTLE_MAX_WAIT_MS)

    async def __aenter__(self) -> Self:
        factory, patchright_active = _get_async_playwright(self._config)
        self._effective_driver = "patchright" if patchright_active else "playwright"
        no_viewport = resolve_no_viewport(self._config)
        if self._config.user_data_dir and not self._config.cdp_url:
            self._profile_lock = acquire_profile_lock(self._config.user_data_dir)
        try:
            self._playwright = await factory().start()
            if self._config.cdp_url:
                self._effective_mode = "cdp"
                self._effective_channel = "attached"
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self._config.cdp_url
                )
                self._context = (
                    self._browser.contexts[0]
                    if self._browser.contexts
                    else await self._browser.new_context()
                )
            elif self._profile_lock is not None:
                self._effective_mode = "persistent"
                self._context, self._effective_channel = (
                    await launch_persistent_context_with_config(
                        self._playwright.chromium,
                        self._profile_lock.profile_dir,
                        self._config,
                        patchright_active,
                    )
                )
                if self._config.stealth and not patchright_active:
                    await self._context.add_init_script(_STEALTH_INIT_SCRIPT)
                if self._context.pages:
                    self._unclaimed_initial_page = self._context.pages[0]
            else:
                self._effective_mode = "fresh"
                self._browser, self._effective_channel = (
                    await launch_browser_with_config(
                        self._playwright.chromium,
                        self._config,
                        patchright_active,
                    )
                )
                context_kwargs: dict[str, Any] = {}
                if no_viewport:
                    context_kwargs["no_viewport"] = True
                if self._config.user_agent:
                    context_kwargs["user_agent"] = self._config.user_agent
                self._context = await self._browser.new_context(**context_kwargs)
                if self._config.stealth and not patchright_active:
                    await self._context.add_init_script(_STEALTH_INIT_SCRIPT)
            logger.debug(
                "Browse session started: driver={}, mode={}, channel={}, headless={}, no_viewport={}",
                self._effective_driver,
                self._effective_mode,
                self._effective_channel,
                None if self._config.cdp_url else self._config.headless,
                None if self._config.cdp_url else no_viewport,
            )
            return self
        except Exception:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        try:
            await self.cleanup()
            if not self._config.cdp_url:
                if self._browser is not None:
                    await self._browser.close()
                elif self._context is not None:
                    await self._context.close()
        finally:
            try:
                if self._playwright is not None:
                    await self._playwright.stop()
            finally:
                if self._profile_lock is not None:
                    self._profile_lock.release()
                    self._profile_lock = None

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
        """Open and navigate a page without adopting user tabs."""
        if (
            self._unclaimed_initial_page is not None
            and not self._unclaimed_initial_page.is_closed()
        ):
            page = self._unclaimed_initial_page
            self._unclaimed_initial_page = None
        else:
            page = await self._context.new_page()
        tab_id = self._register_page(page)
        await page.goto(
            url, wait_until="domcontentloaded", timeout=self._config.timeout_ms
        )
        return await self.tab(tab_id)

    async def list_tabs(self) -> list[OpenTab]:
        """Return metadata for all active tabs."""
        tabs: list[OpenTab] = []
        for tab_id in list(self._owned_pages.keys()):
            try:
                tabs.append(await self.tab(tab_id))
            except (TabGoneError, Exception):
                continue
        return tabs

    async def capture_open_tabs(self) -> list[OpenTab]:
        """Capture final owned-tab and HTML media state before session cleanup."""
        captured: list[OpenTab] = []
        for tab in await self.list_tabs():
            try:
                media_state = await self.media_state(tab.tab_id)
                tab = await self.tab(tab.tab_id)
            except TabGoneError:
                continue
            captured.append(tab.model_copy(update={"media_state": media_state}))
        return captured

    async def media_state(self, tab_id: str) -> list[MediaState] | None:
        """Capture bounded playback state, or ``None`` when the page cannot report it."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        try:
            return _parse_media_state(await page.evaluate(_MEDIA_STATE_JS))
        except PlaywrightError as error:
            logger.warning("Could not capture media state for tab {}: {}", tab_id, error)
            return None

    async def tab(self, tab_id: str) -> OpenTab:
        """Return metadata for an active owned tab or raise ``TabGoneError``."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        target_id = getattr(page, "guid", tab_id)
        title = ""
        try:
            title = await page.title()
        except Exception as error:
            logger.debug("Failed to retrieve title for tab {}: {}", tab_id, error)
        return OpenTab(
            tab_id=tab_id,
            target_id=str(target_id),
            url=page.url,
            title=title,
        )

    async def tab_url(self, tab_id: str) -> str:
        """Return current URL of an owned page without querying title or DOM."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        return page.url

    async def retain_page(self, tab_id: str) -> OpenTab:
        """Preserve one  page after session cleanup."""
        tab = await self.tab(tab_id)
        self._retained_tabs.add(tab_id)
        return tab

    async def close_tab(self, tab_id: str) -> None:
        """Close an owned tab and release its registered state."""
        page = self._owned_pages.pop(tab_id, None)
        self._revisions.pop(tab_id, None)
        self._retained_tabs.discard(tab_id)
        if page is not None and not page.is_closed():
            try:
                await page.close()
            except Exception as error:
                logger.warning("Could not close browser tab {}: {}", tab_id, error)

    async def restore_page(self, tab_id: str, url: str) -> OpenTab:
        """Return an owned page to a previously authorized URL."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        await page.goto(
            url, wait_until="domcontentloaded", timeout=self._config.timeout_ms
        )
        await self._settle_page(page)
        self._revisions[tab_id] += 1
        return await self.tab(tab_id)

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

    async def _settle_page(self, page) -> str:
        """Best-effort wait for a page to stop changing.

        Returns ``"quiet"``, ``"max_wait"`` (page kept changing; expected on
        dynamic sites), ``"timeout"`` or ``"error"``. Never raises.
        """
        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=self._settle_timeout_ms
            )
        except Exception as exc:
            logger.debug(f"Browse settle: load state wait failed: {exc}")
        try:
            status = await asyncio.wait_for(
                page.evaluate(
                    _DOM_QUIET_JS,
                    {"idleMs": self._settle_idle_ms, "maxMs": self._settle_max_wait_ms},
                ),
                timeout=self._settle_max_wait_ms / 1000 + _SETTLE_GRACE_S,
            )
        except asyncio.TimeoutError:
            logger.debug(
                "Browse settle: DOM quiescence check did not return within "
                f"{self._settle_max_wait_ms} ms"
            )
            return "timeout"
        except Exception as exc:
            # Typically "Execution context was destroyed" after a navigation.
            logger.debug(f"Browse settle: DOM quiescence check failed: {exc}")
            return "error"
        return status if status in ("quiet", "max_wait") else "quiet"

    async def snapshot(self, tab_id: str) -> BrowserSnapshot:
        """Create a compact accessibility-oriented observation for one owned tab."""
        page = self._owned_pages.get(tab_id)
        if page is None or page.is_closed():
            raise TabGoneError(tab_id)
        for attempt in range(_SNAPSHOT_ATTEMPTS):
            try:
                return await self._capture_snapshot(tab_id, page)
            except Exception as error:
                if (
                    not _is_navigation_context_error(error)
                    or attempt == _SNAPSHOT_ATTEMPTS - 1
                ):
                    raise
                logger.debug(
                    "Browse snapshot interrupted by navigation on tab {}; retrying",
                    tab_id,
                )
                if page.is_closed():
                    raise TabGoneError(tab_id) from error
                self._revisions[tab_id] += 1
                await self._settle_page(page)
        raise TabGoneError(tab_id)

    async def _capture_snapshot(self, tab_id: str, page: Any) -> BrowserSnapshot:
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
                    href=(
                        entry.get("href")
                        if len(entry.get("href") or "") <= 8192
                        else None
                    ),
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
        viewport = await page.evaluate(_SNAPSHOT_STATE_JS)
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
            media_state=_parse_media_state(viewport.get("media_state", [])),
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
        if action.kind == "open_tab":
            try:
                opened = await self.open_page(action.url or "")
                await self._settle_page(self._owned_pages[opened.tab_id])
                opened = await self.tab(opened.tab_id)
            except Exception as error:
                return BrowserActionResult(success=False, outcome=str(error)[:1000])
            return BrowserActionResult(
                success=True,
                outcome="opened new tab",
                before_url=before_url,
                after_url=opened.url,
                opened_tab_id=opened.tab_id,
            )
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
                input_type = (element.input_type or "").lower() if element else ""
                live_input_type = (await handle.get_attribute("type") or "").lower()
                if input_type == "password" or live_input_type == "password":
                    logger.warning(
                        "Typing into a password field is enabled but experimental "
                        "and not yet validated (tab={}, ref={}).",
                        snapshot.tab_id,
                        action.ref,
                    )
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
