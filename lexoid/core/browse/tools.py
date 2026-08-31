"""Session-scoped Agent Framework tools for read-only browser navigation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from lexoid.core.browse.policy import PolicyDecision, authorize
from lexoid.core.browse.schemas import (
    BrowseTask,
    BrowserAction,
    BrowserActionResult,
    BrowserActionTrace,
    BrowserSnapshot,
)
from lexoid.core.browse.session import GhostBrowserSession

TraceEmitter = Callable[[BrowserActionTrace], Awaitable[None]]


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
        return self._snapshot.model_dump_json(exclude={"content_hash", "truncated"})

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

    async def scroll(self, direction: str = "down") -> str:
        """Scroll the current page up or down to reveal more observed controls."""
        if direction not in {"up", "down"}:
            return json.dumps(
                {"success": False, "outcome": "direction must be up or down"}
            )
        return await self._run(BrowserAction(kind="scroll", text=direction))

    async def back(self) -> str:
        """Navigate back within the same browser tab."""
        return await self._run(BrowserAction(kind="back"))

    async def refresh(self) -> str:
        """Reload the current page."""
        return await self._run(BrowserAction(kind="refresh"))

    async def navigate(self, url: str) -> str:
        """Navigate to an allowlisted URL only."""
        return await self._run(BrowserAction(kind="navigate", url=url))

    def functions(self) -> list[Callable[..., Awaitable[str]]]:
        """Return the callable tools supplied to the navigator Agent."""
        return [
            self.observe,
            self.click,
            self.type,
            self.select,
            self.keypress,
            self.wait,
            self.scroll,
            self.back,
            self.refresh,
            self.navigate,
        ]

    async def _run(self, action: BrowserAction) -> str:
        if self.action_count >= self._task.limits.max_steps:
            return json.dumps(
                {
                    "success": False,
                    "outcome": "navigation step limit reached",
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
        self.action_count += 1
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
            payload["observation"] = json.loads(await self.observe())
        return json.dumps(payload)
