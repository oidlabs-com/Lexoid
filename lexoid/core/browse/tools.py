"""Session-scoped Agent Framework tools for read-only browser navigation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from lexoid.core.browse.policy import PolicyDecision, authorize, is_allowed_url
from lexoid.core.browse.schemas import (
    BrowseErrorCode,
    BrowseTask,
    BrowserAction,
    BrowserActionResult,
    BrowserActionTrace,
    BrowserSnapshot,
    NavigationOutcome,
)
from lexoid.core.browse.session import GhostBrowserSession

TraceEmitter = Callable[[BrowserActionTrace], Awaitable[None]]


def _contains_normalized(haystack: str, needle: str) -> bool:
    """Compare visible text ignoring whitespace and case differences."""
    if not needle.strip():
        return False
    return " ".join(needle.split()).lower() in " ".join(haystack.split()).lower()


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
        self._emit = emit
        self._snapshot: BrowserSnapshot | None = None
        self.action_count = 0
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

    async def observe(self) -> str:
        """Return the current accessible elements available to navigation tools."""
        self._snapshot = await self._session.snapshot(self._tab_id)
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
        clamped_chars = max(100, min(max_chars, 20_000))
        full_text = await self._session.text_content(self._tab_id)
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
        try:
            reported = NavigationOutcome(outcome)
        except ValueError:
            return json.dumps(
                {
                    "success": False,
                    "outcome": "unknown outcome; use results_ready, no_results, "
                    "blocked, or timeout",
                }
            )
        if reported is NavigationOutcome.UNKNOWN:
            return json.dumps(
                {"success": False, "outcome": "unknown is not reportable"}
            )
        # A reported outcome is only accepted when the page still shows the quote.
        if reported in {NavigationOutcome.RESULTS_READY, NavigationOutcome.NO_RESULTS}:
            page_text = await self._session.text_content(self._tab_id)
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
        if self.action_count >= self._task.limits.max_steps:
            self.step_limit_reached = True
            return json.dumps(
                {
                    "success": False,
                    "outcome": "navigation step limit reached; call report_outcome "
                    "now with the outcome you can support",
                }
            )
        if self._snapshot is None:
            await self.observe()
        assert self._snapshot is not None
        action.snapshot_id = self._snapshot.snapshot_id
        decision = authorize(action, self._task.allowed_domains)
        if decision.decision is PolicyDecision.ALLOW:
            result = await self._session.execute(action)
        else:
            result = BrowserActionResult(
                success=False,
                outcome=decision.reason,
                error_code=decision.error_code,
            )
        if result.success:
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
                    current_tab_info = await self._session.tab(self._tab_id)
                    if not is_allowed_url(
                        current_tab_info.url, self._task.allowed_domains
                    ):
                        result = BrowserActionResult(
                            success=False,
                            outcome="navigation destination outside allowlist",
                            error_code=BrowseErrorCode.POLICY_DENIED,
                            before_url=result.before_url,
                            after_url=current_tab_info.url,
                        )
                except Exception:
                    pass
        self.action_count += 1
        if result.success:
            self.successful_action_count += 1
        self.last_error_code = None if result.success else result.error_code
        await self._emit(
            BrowserActionTrace(
                event="action",
                task_id=self._task.task_id,
                tab_id=self._tab_id,
                snapshot_id=self._snapshot.snapshot_id,
                action=action,
                result=result,
            )
        )
        payload = {"action": action.model_dump(), "result": result.model_dump()}
        if result.success:
            if result.opened_tab_id:
                self._tab_id = result.opened_tab_id
            payload["observation"] = json.loads(await self.observe())
        return json.dumps(payload)
