"""Single-task browse orchestration with deterministic evidence handling."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from loguru import logger

from lexoid.core.browse.events import BrowseEventListener, BrowseEventPublisher
from lexoid.core.browse.policy import is_allowed_url
from lexoid.core.browse.schemas import (
    BrowseResult,
    BrowseTask,
    BrowseTaskResult,
    BrowseTerminalState,
    BrowserActionTrace,
    BrowseUsage,
    PageArtifact,
)
from lexoid.core.ghost import GhostConfig, ghost_get_html
from lexoid.core.browse.session import GhostBrowserSession
from lexoid.core.browse.model_provider import ChatClient
from lexoid.core.browse.agents import (
    extract_claims,
    navigate_with_tools,
    synthesize_answer,
)
from lexoid.core.browse.collector import collect_result_pages
from lexoid.core.browse.evidence import validated_claims
from lexoid.core.browse.tools import BrowserToolset

HtmlFetcher = Callable[[str, GhostConfig], tuple[str | None, dict[str, int]]]


def _add_usage(left: BrowseUsage, right: BrowseUsage) -> BrowseUsage:
    """Combine usage across model roles for per-run cost measurement."""
    return BrowseUsage(
        input=left.input + right.input,
        output=left.output + right.output,
        total=left.total + right.total,
    )


async def run_task(
    task: BrowseTask,
    *,
    cdp_url: str | None = None,
    headless: bool = True,
    event_listener: BrowseEventListener | None = None,
    html_fetcher: HtmlFetcher | None = None,
    navigator_client: ChatClient | None = None,
    extractor_client: ChatClient | None = None,
    synthesizer_client: ChatClient | None = None,
) -> BrowseResult:
    """Capture one allowlisted page and return a typed, grounded task result."""
    publisher = BrowseEventPublisher(event_listener)
    fetcher = html_fetcher or ghost_get_html
    agent_usage = BrowseUsage()
    url = task.seed_urls[0]
    logger.debug("Browse task {} started for {}", task.task_id, url)
    if not is_allowed_url(url, task.allowed_domains):
        logger.debug(
            "Browse task {} blocked: seed URL is outside allowlist", task.task_id
        )
        task.status = BrowseTerminalState.BLOCKED
        return BrowseResult(
            task_results=[BrowseTaskResult(task=task, status=task.status)],
            warnings=["Seed URL is outside the task allowlist."],
        )

    cfg = GhostConfig.from_kwargs(
        {
            "cdp_url": cdp_url,
            "headless": headless,
            "auto_scroll": False,
            "timeout_ms": task.limits.timeout_ms,
        }
    )
    if not cfg.enabled:
        cfg.enabled = True
    try:
        if html_fetcher is not None:
            logger.debug(
                "Browse task {} fetching seed URL without navigation", task.task_id
            )
            html, usage = await asyncio.to_thread(fetcher, url, cfg)
            retained_tabs = []
            artifacts = []
            pagination_complete = True
        else:
            async with GhostBrowserSession(cfg) as session:
                tab = await session.open_page(url)
                toolset = BrowserToolset(session, task, tab.tab_id, publisher.emit)
                snapshot = await toolset.observe()
                logger.debug(
                    "Browse task {} captured initial observation on tab {}",
                    task.task_id,
                    tab.tab_id,
                )
                if navigator_client is not None:
                    navigator_usage = await navigate_with_tools(
                        navigator_client, toolset, task, snapshot
                    )
                    agent_usage = _add_usage(agent_usage, navigator_usage)
                artifacts, pagination_complete = await collect_result_pages(
                    session,
                    tab.tab_id,
                    task.limits.max_pages,
                    task.limits.max_artifact_chars,
                )
                html = artifacts[0].text if artifacts else None
                retained_tabs = (
                    [await session.retain_page(tab.tab_id)]
                    if task.retain_final_page
                    else []
                )
                usage = {"input": 0, "output": 0, "total": 0}
    except asyncio.CancelledError:
        logger.debug("Browse task {} cancelled", task.task_id)
        task.status = BrowseTerminalState.CANCELLED
        await publisher.emit(BrowserActionTrace(event="terminal", task_id=task.task_id))
        raise

    normalized_usage = BrowseUsage.model_validate(usage or {})
    if html is None:
        logger.debug(
            "Browse task {} failed: page capture returned no HTML", task.task_id
        )
        task.status = BrowseTerminalState.FAILED
        result = BrowseTaskResult(task=task, status=task.status, usage=normalized_usage)
        await publisher.emit(BrowserActionTrace(event="terminal", task_id=task.task_id))
        return BrowseResult(
            task_results=[result],
            warnings=["Page capture failed."],
            usage=normalized_usage,
        )

    if not artifacts:
        text = html[: task.limits.max_artifact_chars]
        artifacts = [
            PageArtifact(
                artifact_id="artifact-1",
                url=url,
                tab_id=retained_tabs[0].tab_id if retained_tabs else "ephemeral-1",
                content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
                text=text,
                truncated=len(text) < len(html),
            )
        ]
    artifact = artifacts[0]
    logger.debug(
        "Browse task {} captured artifact {} (chars={}, truncated={})",
        task.task_id,
        artifact.artifact_id,
        len(artifact.text),
        artifact.truncated,
    )
    claims = []
    answer = ""
    warnings: list[str] = []
    # Completeness must follow captured evidence, never model narration.
    capture_complete = pagination_complete and not any(
        artifact.truncated for artifact in artifacts
    )
    if extractor_client is not None:
        claims, extractor_usage = await extract_claims(extractor_client, artifacts)
        agent_usage = _add_usage(agent_usage, extractor_usage)
        claims = validated_claims(claims, artifacts)
        logger.debug(
            "Browse task {} validated {} evidence claims", task.task_id, len(claims)
        )
    if synthesizer_client is not None:
        answer, cited_claim_ids, synthesizer_usage = await synthesize_answer(
            synthesizer_client, claims, capture_complete
        )
        agent_usage = _add_usage(agent_usage, synthesizer_usage)
        valid_claim_ids = {claim.claim_id for claim in claims}
        if not set(cited_claim_ids).issubset(valid_claim_ids):
            raise ValueError("synthesizer cited an unknown evidence claim")
        if answer and not cited_claim_ids:
            warnings.append("Answer is not supported by validated evidence claims.")
    if capture_complete:
        task.status = BrowseTerminalState.COMPLETED
    else:
        task.status = BrowseTerminalState.LIMIT_REACHED
        warnings.append(
            "Result pagination or artifact capture reached a limit; results are "
            "not exhaustive and no absence or completeness conclusion is supported."
        )
    normalized_usage = _add_usage(normalized_usage, agent_usage)
    logger.debug(
        "Browse task {} completed with status {} and usage {}",
        task.task_id,
        task.status.value,
        normalized_usage.model_dump(),
    )
    result = BrowseTaskResult(
        task=task,
        status=task.status,
        artifacts=artifacts,
        claims=claims,
        trace=publisher.events,
        retained_tabs=retained_tabs,
        usage=normalized_usage,
    )
    await publisher.emit(BrowserActionTrace(event="artifact", task_id=task.task_id))
    await publisher.emit(BrowserActionTrace(event="terminal", task_id=task.task_id))
    result.trace = publisher.events
    return BrowseResult(
        answer=answer,
        task_results=[result],
        warnings=warnings,
        usage=normalized_usage,
    )
