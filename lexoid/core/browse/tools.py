"""Session-scoped Agent Framework tools for policy-based browser navigation."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from lexoid.core.browse.events import VerificationHandler
from lexoid.core.browse.policy import (
    PolicyDecision,
    authorize,
    fallback_search_domains,
    is_allowed_url,
    normalize_domain,
    search_discovery_domain,
)
from lexoid.core.browse.schemas import (
    BlockedSource,
    BrowseErrorCode,
    BrowserAction,
    BrowserActionResult,
    BrowserActionTrace,
    BrowserSnapshot,
    BrowseTask,
    NavigationOutcome,
    VerificationRequest,
)
from lexoid.core.browse.session import GhostBrowserSession, TabGoneError
from loguru import logger

TraceEmitter = Callable[[BrowserActionTrace], Awaitable[None]]
_MAX_OPEN_TABS = 10
# Passive checks may clear on their own; give them one short chance first.
_VERIFICATION_SETTLE_S = 3.0
_VERIFICATION_POLL_S = 0.5
# Challenges often reload the page after success; require a stable clear state.
_VERIFICATION_CLEAR_STABLE_S = 2.0
_VERIFICATION_CLEAR_MAX_S = 15.0


def _contains_normalized(haystack: str, needle: str) -> bool:
    """Compare visible text ignoring whitespace and case differences."""
    if not needle.strip():
        return False
    return " ".join(needle.split()).lower() in " ".join(haystack.split()).lower()


def _denied_json(outcome: str) -> str:
    """Return a serialized tool failure with a standard failure shape."""
    return json.dumps({"success": False, "outcome": outcome})


def _describe_target_element(snapshot: BrowserSnapshot | None, ref: str | None) -> str:
    """Format element semantic descriptors (role, name, context) with ref."""
    if not ref:
        return ""
    if not snapshot:
        return f"(ref={ref})"
    element = next((e for e in snapshot.elements if e.ref == ref), None)
    if not element:
        return f"(ref={ref})"
    parts = []
    role_or_tag = element.role or element.tag or "element"
    parts.append(role_or_tag)
    if element.name:
        clean_name = " ".join(element.name.split())
        if len(clean_name) > 60:
            clean_name = clean_name[:57] + "..."
        parts.append(f'"{clean_name}"')
    if element.field_context:
        parts.append(f'in "{element.field_context}"')
    if element.in_modal:
        parts.append("(in dialog)")
    return f"{' '.join(parts)} (ref={ref})"


def _format_action_call(action: BrowserAction, snapshot: BrowserSnapshot | None) -> str:
    """Format human-readable representation of a proposed browser action."""
    target = _describe_target_element(snapshot, action.ref)
    if action.kind == "click":
        return f"click {target}".strip()
    if action.kind == "type":
        text_preview = f'"{action.text}"' if action.text else '""'
        return f"type {text_preview} into {target}".strip()
    if action.kind == "select":
        return f'select "{action.text or ""}" from {target}'.strip()
    if action.kind == "hover":
        return f"hover {target}".strip()
    if action.kind == "keypress":
        return f'keypress "{action.text or "Enter"}"'
    if action.kind == "scroll":
        direction = action.text or "down"
        return f"scroll {direction} {target}".strip()
    if action.kind in {"navigate", "open_tab"}:
        verb = "navigate to" if action.kind == "navigate" else "open new tab at"
        return f"{verb} {action.url or ''}"
    if action.kind == "wait":
        return f'wait for "{action.text}"' if action.text else "wait"
    if action.kind in {"back", "refresh", "done", "accept_terms"}:
        return action.kind
    return f"{action.kind} {target}".strip()


# Per-element identifiers are constant across a snapshot, so send them once.
_OBSERVATION_EXCLUDE = {
    "content_hash": True,
    "truncated": True,
    "elements": {"__all__": {"snapshot_id", "tab_id", "frame_id", "node_id"}},
}


class BrowserToolset:
    """Expose only policy-checked operations for one owned browser tab."""

    def __init__(
        self,
        session: GhostBrowserSession,
        task: BrowseTask,
        tab_id: str,
        emit: TraceEmitter,
        verification_handler: VerificationHandler | None = None,
    ) -> None:
        self._session = session
        self._verification_handler = verification_handler
        self._task = task
        self._initial_domains = list(task.allowed_domains)
        self._fallback_search_domains = fallback_search_domains(
            task.seed_urls + [seed.url for seed in task.inferred_seeds],
            self._initial_domains,
            task.source_scope.mode,
        )
        self._search_discovery_domains = (
            self._initial_domains + self._fallback_search_domains
        )
        task.allowed_domains.extend(self._fallback_search_domains)
        self._tab_id = tab_id
        self._openers: dict[str, str] = {}
        self._emit = emit
        self._snapshot: BrowserSnapshot | None = None
        self._quarantined = False
        self.action_count = 0
        self.run_action_count = 0
        self.successful_action_count = 0
        self.outcome = NavigationOutcome.UNKNOWN
        self.outcome_evidence = ""
        # Deterministic executor state, used to explain a navigator exit without
        # a reported outcome; never derived from model text.
        self.step_limit_reached = False
        self.last_error_code: BrowseErrorCode | None = None
        # Provider of an uncompleted challenge; persists across navigator runs.
        self.verification_required: str | None = None
        # Sources that stopped access, keyed by allowlist domain; never cleared by
        # progress on another source.
        self.blocked_sources: dict[str, BlockedSource] = {}

    def source_domain(self, url: str) -> str:
        """Return the allowlist domain covering a URL, else its bare host."""
        matches = [
            normalize_domain(domain)
            for domain in self._task.allowed_domains
            if is_allowed_url(url, [domain])
        ]
        if matches:
            return max(matches, key=len)
        return normalize_domain(url).removeprefix("www.")

    def record_blocked(
        self,
        url: str,
        reason: str,
        *,
        provider: str | None = None,
        detail: str = "",
    ) -> None:
        """Remember that a source stopped access so it is not retried."""
        domain = self.source_domain(url)
        if not domain:
            return
        self.blocked_sources[domain] = BlockedSource.model_validate(
            {
                "domain": domain,
                "url": url[:8_192],
                "reason": reason,
                "provider": provider,
                "detail": detail[:500],
            }
        )

    def is_blocked_url(self, url: str) -> bool:
        """Return whether a URL belongs to a source that already blocked access."""
        return bool(self.blocked_sources) and is_allowed_url(
            url, list(self.blocked_sources)
        )

    def has_unblocked_source(self) -> bool:
        """Return whether any allowlisted source has not blocked access."""
        return any(
            not self.is_blocked_url(f"https://{normalize_domain(domain)}/")
            for domain in self._task.allowed_domains
            if normalize_domain(domain)
        )

    @property
    def fallback_search_domains(self) -> list[str]:
        """Return policy-authorized alternatives, separate from task seeds."""
        return list(self._fallback_search_domains)

    @property
    def tab_id(self) -> str:
        """Return the currently active tab ID."""
        return self._tab_id

    @property
    def is_quarantined(self) -> bool:
        """Return whether this toolset has stopped access after a policy failure."""
        return self._quarantined

    @property
    def remaining_task_actions(self) -> int:
        """Return the number of browser actions left in the task budget."""
        return max(self._task.limits.max_steps - self.action_count, 0)

    @property
    def remaining_actions(self) -> int:
        """Return the remaining actions allowed in this run and task."""
        return min(
            max(self._task.limits.max_steps_per_run - self.run_action_count, 0),
            self.remaining_task_actions,
        )

    def begin_run(self) -> None:
        """Reset navigator-run state without resetting the shared action budget."""
        if self._quarantined:
            return
        self.outcome = NavigationOutcome.UNKNOWN
        self.outcome_evidence = ""
        self.last_error_code = None
        self.run_action_count = 0
        self.step_limit_reached = False

    async def _activate(self, tab_id: str) -> None:
        self._tab_id = tab_id
        activate = getattr(self._session, "activate_tab", None)
        if activate is not None:
            await activate(tab_id)

    async def _get_tab_url(self, tab_id: str) -> str:
        if hasattr(self._session, "tab_url"):
            res = self._session.tab_url(tab_id)
            if inspect.isawaitable(res):
                return await res
            return res  # type: ignore[return-value]
        tab = await self._session.tab(tab_id)
        return tab.url

    async def _handle_bad_tab(self, bad_tab_id: str) -> None:
        try:
            await self._session.close_tab(bad_tab_id)
        except Exception as error:
            logger.warning("Could not close bad tab {}: {}", bad_tab_id, error)

        fallback_tab_id = self._openers.pop(bad_tab_id, None)
        candidate_id = None
        if fallback_tab_id:
            try:
                url = await self._get_tab_url(fallback_tab_id)
                if is_allowed_url(url, self._task.allowed_domains):
                    candidate_id = fallback_tab_id
            except Exception:
                candidate_id = None

        if not candidate_id:
            try:
                open_tabs = await self._session.list_tabs()
                for t in open_tabs:
                    if t.tab_id != bad_tab_id and is_allowed_url(
                        t.url, self._task.allowed_domains
                    ):
                        candidate_id = t.tab_id
                        break
            except Exception as error:
                logger.warning("Failed to list tabs while handling bad tab: {}", error)

        if candidate_id:
            logger.info(
                "Closed off-scope tab {} and switched back to safe tab {}",
                bad_tab_id,
                candidate_id,
            )
            await self._activate(candidate_id)
            self._snapshot = None
        else:
            logger.warning(
                "No safe tabs remain after closing bad tab {}; quarantining toolset",
                bad_tab_id,
            )
            self._quarantined = True
            self.outcome = NavigationOutcome.BLOCKED
            self.last_error_code = BrowseErrorCode.TAB_GONE

    async def _restore_allowed_source(self, tab_id: str, source_url: str) -> str | None:
        if not is_allowed_url(source_url, self._task.allowed_domains):
            return None
        restore_page = getattr(self._session, "restore_page", None)
        if restore_page is None:
            return None
        try:
            restored_tab = await restore_page(tab_id, source_url)
        except Exception as error:
            logger.warning(
                "Could not restore tab {} to its allowlisted source {}: {}",
                tab_id,
                source_url,
                error,
            )
            return None
        if not is_allowed_url(restored_tab.url, self._task.allowed_domains):
            logger.warning(
                "Restoring tab {} landed outside the task allowlist: {}",
                tab_id,
                restored_tab.url,
            )
            return None
        self._snapshot = None
        return restored_tab.url

    async def _active_tab_allowed(self) -> bool:
        if self._quarantined:
            return False
        try:
            url = await self._get_tab_url(self._tab_id)
        except TabGoneError:
            logger.warning("Active tab {} is gone", self._tab_id)
            await self._handle_bad_tab(self._tab_id)
            return False
        except Exception as error:
            logger.warning("Could not verify active tab {}: {}", self._tab_id, error)
            return False
        if not is_allowed_url(url, self._task.allowed_domains):
            logger.warning(
                "Active tab {} is outside the task allowlist: {}", self._tab_id, url
            )
            await self._handle_bad_tab(self._tab_id)
            return False
        return True

    async def quarantine(self) -> None:
        """Close the active tab and stop further navigation after an unrecoverable policy failure."""
        self._quarantined = True
        self.outcome = NavigationOutcome.BLOCKED
        self.last_error_code = BrowseErrorCode.TAB_GONE
        try:
            await self._session.close_tab(self._tab_id)
        except Exception as error:
            logger.warning(
                "Could not close quarantined tab {}: {}", self._tab_id, error
            )

    async def observe(self) -> str:
        """Return the current accessible elements available to navigation tools."""
        if not await self._active_tab_allowed():
            return _denied_json("active tab is outside the task allowlist")
        if self.remaining_actions and await self._session.skip_ad(self._tab_id):
            self.action_count += 1
            self.run_action_count += 1
            logger.info("|   [OK] Skipped ad")
            await self._emit(
                BrowserActionTrace(
                    event="action",
                    task_id=self._task.task_id,
                    tab_id=self._tab_id,
                    metadata={"automatic_ad_skip": True},
                )
            )
        snapshot = await self._session.snapshot(self._tab_id)
        if not await self._active_tab_allowed():
            return _denied_json("active tab is outside the task allowlist")
        self._snapshot = snapshot
        await self._emit(
            BrowserActionTrace(
                event="observation",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                snapshot_id=self._snapshot.snapshot_id,
            )
        )
        return self._snapshot.model_dump_json(exclude=_OBSERVATION_EXCLUDE)

    async def read_text(self, max_chars: int = 4000) -> str:
        """Read visible rendered page text to inspect static text, tables, and messages.

        Does not count toward the browser action modification count. Returns bounded
        visible text from the current page.
        """
        if not await self._active_tab_allowed():
            return _denied_json("active tab is outside the task allowlist")
        clamped_chars = max(100, min(max_chars, 20_000))
        full_text = await self._session.text_content(self._tab_id)
        if not await self._active_tab_allowed():
            return _denied_json("active tab is outside the task allowlist")
        bounded_text = full_text[:clamped_chars]
        truncated = len(full_text) > clamped_chars
        payload = {
            "text": bounded_text,
            "total_chars": len(full_text),
            "truncated": truncated,
        }
        await self._emit(
            BrowserActionTrace(
                event="observation",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                snapshot_id=self._snapshot.snapshot_id if self._snapshot else None,
                metadata={
                    "action": "read_text",
                    "chars": len(bounded_text),
                    "truncated": truncated,
                },
            )
        )
        return json.dumps(payload)

    async def click(self, ref: str) -> str:
        """Click an observed element; search-provider links can admit their HTTPS destination domain."""
        return await self._run(BrowserAction(kind="click", ref=ref))

    async def type(self, ref: str, text: str) -> str:
        """Replace the value of an observed text field; never use for credentials."""
        return await self._run(BrowserAction(kind="type", ref=ref, text=text))

    async def select(self, ref: str, text: str) -> str:
        """Select an option from an observed native or custom dropdown."""
        return await self._run(BrowserAction(kind="select", ref=ref, text=text))

    async def keypress(self, keys: str = "Enter") -> str:
        """Send a case-sensitive Playwright key or shortcut to the current page.

        Use exact key names: Enter, Escape, Tab, Backspace, ArrowDown.
        Use '+' for shortcuts, e.g. Control+a or Meta+a. Use Enter, not ENTER.
        """
        return await self._run(BrowserAction(kind="keypress", text=keys))

    async def wait(self, text: str = "") -> str:
        """Wait briefly, or until visible text appears when text is supplied."""
        return await self._run(BrowserAction(kind="wait", text=text or None))

    async def scroll(self, direction: str = "down", ref: str | None = None) -> str:
        """Scroll the page or a specific container/modal up or down to reveal more observed controls."""
        if direction not in {"up", "down"}:
            return json.dumps(
                {"success": False, "outcome": "direction must be up or down"}
            )
        return await self._run(BrowserAction(kind="scroll", text=direction, ref=ref))

    async def back(self) -> str:
        """Navigate back within the same browser tab."""
        return await self._run(BrowserAction(kind="back"))

    async def refresh(self) -> str:
        """Reload the current page."""
        return await self._run(BrowserAction(kind="refresh"))

    async def navigate(self, url: str) -> str:
        """Navigate to an allowlisted URL only."""
        if self.is_blocked_url(url):
            return self._blocked_source_json(url)
        return await self._run(BrowserAction(kind="navigate", url=url))

    async def open_tab(self, url: str) -> str:
        """Open an allowlisted HTTPS URL in a new tab and switch to it."""
        if self.is_blocked_url(url):
            return self._blocked_source_json(url)
        tabs = await self._session.list_tabs()
        existing = next(
            (t for t in tabs if t.url.split("#")[0] == url.split("#")[0]), None
        )
        if existing is not None:
            return await self.switch_tab(existing.tab_id)
        if len(tabs) >= _MAX_OPEN_TABS:
            return json.dumps(
                {
                    "success": False,
                    "outcome": f"open-tab limit reached ({_MAX_OPEN_TABS})",
                }
            )
        return await self._run(BrowserAction(kind="open_tab", url=url))

    def _blocked_source_json(self, url: str) -> str:
        domain = self.source_domain(url)
        return json.dumps(
            {
                "success": False,
                "error_code": BrowseErrorCode.SOURCE_BLOCKED.value,
                "outcome": f"{domain} already blocked access in this task; do not "
                "retry it. Continue with other permitted sources, or report the "
                "block if none remain.",
            }
        )

    async def ensure_live_tab(self) -> bool:
        """Move off a closed or crashed active tab; return whether a live tab remains."""
        if self._quarantined:
            return False
        try:
            await self._get_tab_url(self._tab_id)
            return True
        except TabGoneError:
            logger.warning("Active tab {} is gone; switching tabs", self._tab_id)
            await self._handle_bad_tab(self._tab_id)
            return not self._quarantined

    async def leave_blocked_tab(self) -> None:
        """Switch off a blocked source's tab to an open, unblocked allowlisted tab."""
        if self._quarantined:
            return
        try:
            if not self.is_blocked_url(await self._get_tab_url(self._tab_id)):
                return
        except TabGoneError:
            pass
        for tab in await self._session.list_tabs():
            if is_allowed_url(
                tab.url, self._task.allowed_domains
            ) and not self.is_blocked_url(tab.url):
                await self._activate(tab.tab_id)
                self._snapshot = None
                return

    async def list_tabs(self) -> str:
        """List active tabs to inspect open pages."""
        if self._quarantined:
            return _denied_json("browser toolset is quarantined")
        tabs = await self._session.list_tabs()
        return json.dumps(
            [
                {
                    "tab_id": tab.tab_id,
                    "url": tab.url,
                    "title": tab.title,
                    "active": tab.tab_id == self._tab_id,
                }
                for tab in tabs
            ]
        )

    async def switch_tab(self, tab_id: str) -> str:
        """Switch active interaction to an open tab."""
        if self._quarantined:
            return _denied_json("browser toolset is quarantined")
        tabs = await self._session.list_tabs()
        matched = next((t for t in tabs if t.tab_id == tab_id), None)
        if matched is None:
            return json.dumps(
                {
                    "success": False,
                    "outcome": f"tab {tab_id} not found among active owned tabs",
                }
            )
        if not is_allowed_url(matched.url, self._task.allowed_domains):
            return json.dumps(
                {
                    "success": False,
                    "outcome": f"tab {tab_id} destination outside allowlist",
                }
            )
        await self._activate(tab_id)
        await self._emit(
            BrowserActionTrace(
                event="observation",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                metadata={"action": "switch_tab", "switched_to": tab_id},
            )
        )
        obs = json.loads(await self.observe())
        return json.dumps(
            {
                "success": True,
                "outcome": f"switched to tab {tab_id} ({matched.url})",
                "observation": obs,
            }
        )

    async def report_outcome(self, outcome: str, evidence: str) -> str:
        """Report the final navigation state, quoting visible page text as evidence."""
        if not await self._active_tab_allowed():
            return _denied_json("active tab is outside the task allowlist")
        try:
            reported = NavigationOutcome(outcome)
        except ValueError:
            return json.dumps(
                {
                    "success": False,
                    "outcome": "unknown outcome; use results_ready, no_results, "
                    "blocked, timeout, or budget_exhausted",
                }
            )
        if reported is NavigationOutcome.UNKNOWN:
            return json.dumps(
                {"success": False, "outcome": "unknown is not reportable"}
            )
        # A reported outcome is only accepted when the page still shows the quote.
        if reported in {NavigationOutcome.RESULTS_READY, NavigationOutcome.NO_RESULTS}:
            page_text = await self._session.text_content(self._tab_id)
            if not await self._active_tab_allowed():
                return _denied_json("active tab is outside the task allowlist")
            if not _contains_normalized(page_text, evidence):
                return json.dumps(
                    {
                        "success": False,
                        "outcome": "evidence is not visible page text; observe the "
                        "page and quote it exactly",
                    }
                )
        if reported in {NavigationOutcome.RESULTS_READY, NavigationOutcome.NO_RESULTS}:
            # A verified outcome, e.g. via a fallback provider, supersedes the block.
            self.verification_required = None
        elif reported in {NavigationOutcome.BLOCKED, NavigationOutcome.TIMEOUT}:
            blocked_url = await self._get_tab_url(self._tab_id)
            # Keep a more specific verification record for the same source.
            if self.source_domain(blocked_url) not in self.blocked_sources:
                self.record_blocked(blocked_url, reported.value, detail=evidence)
        self.outcome = reported
        self.outcome_evidence = evidence[:1000]
        await self._emit(
            BrowserActionTrace(
                event="observation",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                metadata={"navigation_outcome": reported.value},
            )
        )
        return json.dumps({"success": True, "outcome": reported.value})

    def functions(self) -> list[Callable[..., Awaitable[str]]]:
        """Return the callable tools supplied to the navigator Agent."""
        return [
            self.observe,
            self.read_text,
            self.click,
            self.type,
            self.select,
            self.keypress,
            self.wait,
            self.scroll,
            self.back,
            self.refresh,
            self.navigate,
            self.open_tab,
            self.list_tabs,
            self.switch_tab,
            self.report_outcome,
        ]

    async def _run(self, action: BrowserAction) -> str:
        safe_action = (
            action.model_copy(update={"text": "[redacted]"})
            if action.kind == "type"
            else action
        )
        if not await self._active_tab_allowed():
            result = BrowserActionResult(
                success=False,
                outcome="active tab is outside the task allowlist",
                error_code=BrowseErrorCode.POLICY_DENIED,
            )
            return json.dumps(
                {"action": safe_action.model_dump(), "result": result.model_dump()}
            )
        if self.remaining_actions == 0:
            self.step_limit_reached = True
            logger.warning(
                "Browse action budget exhausted (run {}/{}, task {}/{}); rejected {}",
                self.run_action_count,
                self._task.limits.max_steps_per_run,
                self.action_count,
                self._task.limits.max_steps,
                action.kind,
            )
            return json.dumps(
                {
                    "success": False,
                    "outcome": "browser action budget exhausted; call "
                    "report_outcome('budget_exhausted', ...) unless the current "
                    "page shows a separate site blocker",
                }
            )
        if self._snapshot is None:
            await self.observe()
        assert self._snapshot is not None
        action.snapshot_id = self._snapshot.snapshot_id
        call_desc = _format_action_call(safe_action, self._snapshot)
        logger.info(
            "+-- Step {} [run {}/{}, task {}/{}]",
            self.action_count + 1,
            self.run_action_count + 1,
            self._task.limits.max_steps_per_run,
            self.action_count + 1,
            self._task.limits.max_steps,
        )
        logger.info("|   > {}", call_desc)
        await self._emit(
            BrowserActionTrace(
                event="decision",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                snapshot_id=self._snapshot.snapshot_id,
                metadata={
                    "role": "navigator",
                    "question": "Choose the next safe browser operation and observed target, or stop.",
                    "state_ref": {"snapshot_id": self._snapshot.snapshot_id},
                    "options": {
                        "operations": [
                            "click",
                            "type",
                            "select",
                            "keypress",
                            "hover",
                            "scroll",
                            "navigate",
                            "open_tab",
                            "back",
                            "refresh",
                            "wait",
                            "done",
                        ],
                        "element_count": len(self._snapshot.elements),
                        "selected_ref": action.ref,
                    },
                    "selected": {"kind": action.kind, "ref": action.ref},
                },
            )
        )
        decision = authorize(action, self._task.allowed_domains)
        source_url = await self._get_tab_url(self._tab_id)
        snapshot_url = self._snapshot.url
        element = next(
            (item for item in self._snapshot.elements if item.ref == action.ref), None
        )
        discovered_domain = None
        discovery_diagnostics: dict[str, object] = {}
        restored_after_denial = False
        if decision.decision is PolicyDecision.ALLOW:
            result = await self._session.execute(action)
        else:
            result = BrowserActionResult(
                success=False,
                outcome=decision.reason,
                error_code=decision.error_code,
            )

        def admit_search_destination(destination_url: str) -> str | None:
            if action.kind != "click":
                return None
            discovery_diagnostics.update(
                {
                    "source_url": source_url,
                    "snapshot_url": snapshot_url,
                    "source_matches_snapshot": source_url == snapshot_url,
                    "href": element.href if element is not None else None,
                    "destination_url": destination_url,
                    "execution_success": result.success,
                    "initial_domains": list(self._initial_domains),
                    "source_scope": self._task.source_scope.model_dump(),
                    "fallback_search_domains": self.fallback_search_domains,
                    "allowed_domains_before": list(self._task.allowed_domains),
                }
            )
            if not result.success:
                reason = "action_failed"
            elif source_url != snapshot_url:
                reason = "source_snapshot_url_mismatch"
            elif is_allowed_url(destination_url, self._task.allowed_domains):
                reason = "destination_already_allowed"
            else:
                reason = "checking_search_discovery"
            discovery_diagnostics["decision"] = reason
            logger.debug("Search discovery check: {}", discovery_diagnostics)
            if reason != "checking_search_discovery":
                return None
            domain = search_discovery_domain(
                source_url,
                element.href if element is not None else None,
                destination_url,
                self._search_discovery_domains,
                self._task.source_scope.mode,
            )
            if domain:
                self._task.allowed_domains.append(domain)
                logger.info(
                    "Admitted search-discovered domain {} from {}", domain, source_url
                )
            discovery_diagnostics["decision"] = (
                "admitted" if domain else "search_discovery_policy_rejected"
            )
            logger.debug("Search discovery decision: {}", discovery_diagnostics)
            return domain

        if result.opened_tab_id:
            discovered_domain = admit_search_destination(result.after_url)
            if not is_allowed_url(result.after_url, self._task.allowed_domains):
                await self._session.close_tab(result.opened_tab_id)
                result = BrowserActionResult(
                    success=False,
                    outcome="popup destination outside allowlist",
                    error_code=BrowseErrorCode.POLICY_DENIED,
                    before_url=result.before_url,
                    after_url=result.before_url,
                )
        else:
            try:
                current_url = await self._get_tab_url(self._tab_id)
                discovered_domain = admit_search_destination(current_url)
                if not is_allowed_url(current_url, self._task.allowed_domains):
                    restored_url = await self._restore_allowed_source(
                        self._tab_id, source_url
                    )
                    if restored_url is None:
                        await self._handle_bad_tab(self._tab_id)
                    else:
                        restored_after_denial = True
                    result = BrowserActionResult(
                        success=False,
                        outcome=(
                            "navigation destination outside allowlist; "
                            "restored previous page"
                            if restored_url
                            else "navigation destination outside allowlist"
                        ),
                        error_code=BrowseErrorCode.POLICY_DENIED,
                        before_url=result.before_url,
                        after_url=restored_url or current_url,
                        warnings=(
                            ["Restored the allowlisted source page."]
                            if restored_url
                            else []
                        ),
                    )
            except TabGoneError:
                await self._handle_bad_tab(self._tab_id)
                result = BrowserActionResult(
                    success=False,
                    outcome="active tab closed",
                    error_code=BrowseErrorCode.TAB_GONE,
                    before_url=result.before_url,
                    after_url=result.after_url,
                )
            except Exception as error:
                logger.warning(
                    "Could not verify navigation destination for tab {}: {}",
                    self._tab_id,
                    error,
                )
                result = BrowserActionResult(
                    success=False,
                    outcome="unable to verify navigation destination",
                    error_code=BrowseErrorCode.POLICY_DENIED,
                    before_url=result.before_url,
                    after_url=result.after_url,
                )
        self.action_count += 1
        self.run_action_count += 1
        if result.success:
            self.successful_action_count += 1
        self.last_error_code = None if result.success else result.error_code
        if result.success:
            url_part = f" (URL: {result.after_url})" if result.after_url else ""
            tab_part = (
                f" [opened tab {result.opened_tab_id}]" if result.opened_tab_id else ""
            )
            logger.info("|   [OK] Success{}{}", url_part, tab_part)
        else:
            err_code = (
                result.error_code.value
                if result.error_code is not None and hasattr(result.error_code, "value")
                else result.error_code
            )
            code_part = f" (code={err_code})" if err_code else ""
            logger.info("|   [FAIL] {}{}", result.outcome, code_part)
        fallback_used = (
            result.success
            and bool(result.after_url)
            and is_allowed_url(result.after_url, self._fallback_search_domains)
            and not is_allowed_url(result.after_url, self._initial_domains)
        )
        if fallback_used:
            logger.info("Using policy-authorized search fallback {}", result.after_url)
        await self._emit(
            BrowserActionTrace(
                event="action",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                snapshot_id=self._snapshot.snapshot_id
                if self._snapshot is not None
                else None,
                action=safe_action,
                result=result,
                metadata={
                    "description": call_desc,
                    **(
                        {
                            "fallback_search_domains": self.fallback_search_domains,
                            "search_fallback_used": fallback_used,
                        }
                        if self._fallback_search_domains
                        else {}
                    ),
                    **(
                        {"discovery_check": discovery_diagnostics}
                        if discovery_diagnostics
                        else {}
                    ),
                    **(
                        {
                            "discovered_domain": discovered_domain,
                            "discovery_source": source_url,
                            "discovery_href": element.href,
                        }
                        if discovered_domain and element is not None
                        else {}
                    ),
                },
            )
        )
        payload = {"action": safe_action.model_dump(), "result": result.model_dump()}
        if (result.success or restored_after_denial) and result.opened_tab_id:
            self._openers[result.opened_tab_id] = self._tab_id
            await self._activate(result.opened_tab_id)
        verification = await self._resolve_verification()
        if verification is not None:
            payload["verification"] = verification
        if verification is not None and verification["status"] == "required":
            return json.dumps(payload)
        if result.success or restored_after_denial or verification is not None:
            payload["observation"] = json.loads(await self.observe())
        return json.dumps(payload)

    async def _challenge_cleared(
        self, detect: Callable[[str], Awaitable[str | None]]
    ) -> bool:
        """Return whether the challenge stays gone after the page settles."""
        deadline = time.monotonic() + _VERIFICATION_CLEAR_MAX_S
        settle = getattr(self._session, "settle", None)
        try:
            if settle is not None:
                await asyncio.wait_for(
                    settle(self._tab_id), timeout=_VERIFICATION_CLEAR_MAX_S
                )
            clear_since: float | None = None
            while True:
                remaining = max(deadline - time.monotonic(), 0.1)
                provider = await asyncio.wait_for(
                    detect(self._tab_id), timeout=remaining
                )
                now = time.monotonic()
                if provider is None:
                    clear_since = now if clear_since is None else clear_since
                    if now - clear_since >= _VERIFICATION_CLEAR_STABLE_S:
                        return True
                else:
                    clear_since = None
                if now >= deadline:
                    return False
                await asyncio.sleep(_VERIFICATION_POLL_S)
        except TimeoutError:
            return False

    async def _resolve_verification(self) -> dict[str, Any] | None:
        """Hand a blocking site challenge to a person, or block the task."""
        detect = getattr(self._session, "verification_challenge", None)
        if detect is None:
            return None
        try:
            provider = await detect(self._tab_id)
            deadline = time.monotonic() + _VERIFICATION_SETTLE_S
            while provider and time.monotonic() < deadline:
                await asyncio.sleep(_VERIFICATION_POLL_S)
                provider = await detect(self._tab_id)
            if provider is None:
                return None
            url = await self._get_tab_url(self._tab_id)
        except TabGoneError:
            return None
        request = VerificationRequest(
            task_id=self._task.task_id, tab_id=self._tab_id, url=url, provider=provider
        )
        logger.warning("Human verification ({}) required on {}", provider, url)
        await self._emit(
            BrowserActionTrace(
                event="warning",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                metadata={"verification_required": request.model_dump()},
            )
        )
        timeout_ms = self._task.limits.verification_timeout_ms
        verification_timed_out = False
        # A person already had their chance on this source; don't prompt again.
        already_blocked = self.is_blocked_url(url)
        if self._verification_handler is not None and not already_blocked:
            await self._activate(self._tab_id)
            try:
                completed = await asyncio.wait_for(
                    self._verification_handler(request), timeout=timeout_ms / 1000
                )
                cleared = completed and await self._challenge_cleared(detect)
            except TabGoneError:
                return None
            except TimeoutError:
                logger.warning(
                    "Human verification handler timed out after {} ms", timeout_ms
                )
                verification_timed_out = True
                cleared = False
            except Exception as error:
                logger.warning("Verification handler failed: {}", error)
                cleared = False
            if cleared:
                self.verification_required = None
                self.blocked_sources.pop(self.source_domain(url), None)
                self._snapshot = None
                await self._emit(
                    BrowserActionTrace(
                        event="observation",
                        task_id=self._task.task_id,
                        tab_id=self._tab_id,
                        metadata={"verification_completed": provider},
                    )
                )
                return {
                    "status": "completed_by_user",
                    "provider": provider,
                    "outcome": "a person completed the site verification; the page "
                    "may already show results, so check the observation before "
                    "repeating any submission",
                }
        self.verification_required = provider
        self.record_blocked(url, "verification_required", provider=provider)
        self.outcome = NavigationOutcome.BLOCKED
        self.last_error_code = BrowseErrorCode.VERIFICATION_REQUIRED
        next_step = (
            "Do not interact with the challenge or retry this site. If the task "
            "needs other sites, continue with them; otherwise use a permitted "
            "alternative only if source_scope allows it, else call "
            "report_outcome('blocked', ...)"
        )
        if verification_timed_out:
            outcome = (
                f"the human verification handler timed out after {timeout_ms} ms; "
                f"the challenge was not completed. {next_step}"
            )
        else:
            outcome = (
                "the site requires human verification that was not completed. "
                f"{next_step}"
            )
        return {
            "status": "required",
            "provider": provider,
            "error_code": BrowseErrorCode.VERIFICATION_REQUIRED.value,
            "outcome": outcome,
        }
