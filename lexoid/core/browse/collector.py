"""Deterministic single-page result capture for browser search sessions."""

from __future__ import annotations

import hashlib

from loguru import logger

from lexoid.core.browse.schemas import PageArtifact
from lexoid.core.browse.session import GhostBrowserSession
from lexoid.core.utils import html_to_markdown


async def capture_page(
    session: GhostBrowserSession,
    tab_id: str,
    artifact_index: int,
    max_artifact_chars: int,
) -> PageArtifact:
    """Capture the current page as one markdown artifact; loop control lives in the caller."""
    tab = await session.tab(tab_id)
    html = await session.content(tab_id)
    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    markdown = html_to_markdown(html, tab.title, tab.url)["raw"]
    logger.debug(f"Raw markdown result:\n\n{markdown}")
    text = markdown[:max_artifact_chars]
    logger.debug(
        "Browse collector captured page {} url={} hash={} chars={} truncated={}",
        artifact_index,
        tab.url,
        content_hash[:12],
        len(text),
        len(text) < len(markdown),
    )
    return PageArtifact(
        artifact_id=f"artifact-{artifact_index}",
        url=tab.url,
        tab_id=tab_id,
        content_hash=content_hash,
        text=text,
        truncated=len(text) < len(markdown),
    )
