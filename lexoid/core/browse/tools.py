"""Session-scoped Agent Framework tools for policy-based browser navigation."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable

from lexoid.core.browse.policy import PolicyDecision, authorize, is_allowed_url
from lexoid.core.browse.schemas import (
    BrowseErrorCode,
    BrowserAction,
    BrowserActionResult,
    BrowserActionTrace,
    BrowserSnapshot,
    BrowseTask,
    NavigationOutcome,
)
from lexoid.core.browse.session import GhostBrowserSession, TabGoneError
from loguru import logger

TraceEmitter = Callable[[BrowserActionTrace], Awaitable[None]]


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
    if action.kind == "navigate":
        return f"navigate to {action.url or ''}"
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
    ) -> None:
        self._session = session
        self._task = task
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
            self._tab_id = candidate_id
            self._snapshot = None
        else:
            logger.warning(
                "No safe tabs remain after closing bad tab {}; quarantining toolset",
                bad_tab_id,
            )
            self._quarantined = True
            self.outcome = NavigationOutcome.BLOCKED
            self.last_error_code = BrowseErrorCode.TAB_GONE

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
        """Click one element ref returned by observe."""
        return await self._run(BrowserAction(kind="click", ref=ref))

    async def type(self, ref: str, text: str) -> str:
        """Replace the value of an observed text field; never use for credentials."""
        return await self._run(BrowserAction(kind="type", ref=ref, text=text))

    async def select(self, ref: str, text: str) -> str:
        """Select an option from an observed native or custom dropdown."""
        return await self._run(BrowserAction(kind="select", ref=ref, text=text))

    async def keypress(self, keys: str = "Enter") -> str:
        """Send a keyboard shortcut to the current page."""
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
        return await self._run(BrowserAction(kind="navigate", url=url))

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
        self._tab_id = tab_id
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
        if decision.decision is PolicyDecision.ALLOW:
            result = await self._session.execute(action)
        else:
            result = BrowserActionResult(
                success=False,
                outcome=decision.reason,
                error_code=decision.error_code,
            )
        if result.opened_tab_id:
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
                if not is_allowed_url(current_url, self._task.allowed_domains):
                    await self._handle_bad_tab(self._tab_id)
                    result = BrowserActionResult(
                        success=False,
                        outcome="navigation destination outside allowlist",
                        error_code=BrowseErrorCode.POLICY_DENIED,
                        before_url=result.before_url,
                        after_url=current_url,
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
                metadata={"description": call_desc},
            )
        )
        payload = {"action": safe_action.model_dump(), "result": result.model_dump()}
        if result.success:
            if result.opened_tab_id:
                self._openers[result.opened_tab_id] = self._tab_id
                self._tab_id = result.opened_tab_id
            payload["observation"] = json.loads(await self.observe())
        return json.dumps(payload)
