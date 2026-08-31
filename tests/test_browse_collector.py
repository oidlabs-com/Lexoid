"""Deterministic tests for result-page collection."""

import pytest

from lexoid.core.browse.collector import collect_result_pages
from lexoid.core.browse.schemas import OpenTab


class FakeSession:
    """Small paginated session fake without a browser dependency."""

    def __init__(self, pages: list[str]) -> None:
        self.pages = pages
        self.index = 0

    async def tab(self, tab_id: str) -> OpenTab:
        return OpenTab(
            tab_id=tab_id,
            target_id=tab_id,
            url=f"https://example.test/results?page={self.index + 1}",
        )

    async def content(self, tab_id: str) -> str:
        return self.pages[self.index]

    async def advance_to_next_result_page(self, tab_id: str) -> bool:
        if self.index == len(self.pages) - 1:
            return False
        self.index += 1
        return True


@pytest.mark.asyncio
async def test_collector_captures_all_pages_when_next_is_exhausted():
    artifacts, complete = await collect_result_pages(
        FakeSession(["first result", "second result"]), "tab-1", 5, 100
    )

    assert complete is True
    assert [artifact.text for artifact in artifacts] == [
        "first result",
        "second result",
    ]


@pytest.mark.asyncio
async def test_collector_marks_capture_incomplete_at_page_limit():
    artifacts, complete = await collect_result_pages(
        FakeSession(["first result", "second result"]), "tab-1", 1, 100
    )

    assert complete is False
    assert len(artifacts) == 1
