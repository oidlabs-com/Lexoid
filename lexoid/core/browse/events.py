"""Internal async event publication for browse lifecycle telemetry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from lexoid.core.browse.schemas import BrowserActionTrace

BrowseEventListener = Callable[[BrowserActionTrace], Awaitable[None] | None]


class BrowseEventPublisher:
    """Publish typed browse events to optional in-process listeners."""

    def __init__(self, listener: BrowseEventListener | None = None) -> None:
        self._listener = listener
        self.events: list[BrowserActionTrace] = []

    async def emit(self, event: BrowserActionTrace) -> None:
        """Record and optionally publish one event."""
        self.events.append(event)
        if self._listener is None:
            return
        result = self._listener(event)
        if result is not None:
            await result
