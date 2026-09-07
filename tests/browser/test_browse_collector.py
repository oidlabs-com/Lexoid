"""Deterministic tests for single-page result capture."""

import pytest

from lexoid.core.browse.collector import capture_page
from lexoid.core.browse.schemas import OpenTab


class FakeSession:
    """Small session fake without a browser dependency."""

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


@pytest.mark.asyncio
async def test_capture_page_returns_one_markdown_artifact():
    artifact = await capture_page(FakeSession(["first result"]), "tab-1", 1, 100)

    assert artifact.text == "first result"
    assert artifact.artifact_id == "artifact-1"
    assert artifact.truncated is False


@pytest.mark.asyncio
async def test_capture_page_marks_truncation_at_char_limit():
    artifact = await capture_page(
        FakeSession(["a result that is longer than the limit"]), "tab-1", 1, 10
    )

    assert artifact.truncated is True
    assert len(artifact.text) == 10


@pytest.mark.asyncio
async def test_capture_page_stores_markdown_rather_than_raw_html():
    artifact = await capture_page(
        FakeSession(
            ["<html><body><h1>Results</h1><p>Rosina Samadani</p></body></html>"]
        ),
        "tab-1",
        1,
        1_000,
    )

    assert "Rosina Samadani" in artifact.text
    assert "<h1>" not in artifact.text


@pytest.mark.asyncio
async def test_capture_page_hash_reflects_underlying_content():
    session = FakeSession(["same result"])
    first = await capture_page(session, "tab-1", 1, 100)
    second = await capture_page(session, "tab-1", 2, 100)

    assert first.content_hash == second.content_hash
    assert first.artifact_id != second.artifact_id
