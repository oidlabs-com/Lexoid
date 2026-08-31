"""Deterministic result-page capture for completed browser searches."""

from __future__ import annotations

import hashlib

from lexoid.core.browse.schemas import PageArtifact
from lexoid.core.browse.session import GhostBrowserSession


async def collect_result_pages(
    session: GhostBrowserSession, tab_id: str, max_pages: int, max_artifact_chars: int
) -> tuple[list[PageArtifact], bool]:
    """Capture reachable result pages and report whether pagination was exhausted."""
    artifacts: list[PageArtifact] = []
    exhausted = False
    for index in range(max_pages):
        tab = await session.tab(tab_id)
        html = await session.content(tab_id)
        text = html[:max_artifact_chars]
        artifacts.append(
            PageArtifact(
                artifact_id=f"artifact-{index + 1}",
                url=tab.url,
                tab_id=tab_id,
                content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
                text=text,
                truncated=len(text) < len(html),
            )
        )
        if not await session.advance_to_next_result_page(tab_id):
            exhausted = True
            break
    return artifacts, exhausted
