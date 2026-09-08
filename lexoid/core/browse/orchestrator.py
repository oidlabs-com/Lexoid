"""Single-task browse orchestration with deterministic evidence handling."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from loguru import logger

from lexoid.core.browse.events import BrowseEventListener, BrowseEventPublisher
from lexoid.core.browse.policy import is_allowed_url
from lexoid.core.browse.profiles import find_profile
from lexoid.core.browse.schemas import (
    BrowseResult,
    BrowseTask,
    BrowseTaskResult,
    BrowseTerminalState,
    BrowserActionTrace,
    BrowseUsage,
    CoverageReport,
    EvidenceAssessment,
    EvidenceClaim,
    NavigationOutcome,
    PageArtifact,
)
from lexoid.core.ghost import GhostConfig, ghost_get_html
from lexoid.core.browse.session import GhostBrowserSession
from lexoid.core.browse.model_provider import ChatClient
from lexoid.core.browse.agents import (
    assess_page,
    extract_claims,
    navigate_with_tools,
    synthesize_answer,
)
from lexoid.core.browse.collector import capture_page
from lexoid.core.browse.evidence import validated_claims, verify_constraints
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
    """Capture one allowlisted page and return a typed, grounded task result.

    ``extractor_client`` drives two different flows depending on the capture
    path: the non-interactive ``html_fetcher`` path runs a single end-of-capture
    ``extract_claims`` call; the live browser-session path instead drives
    ``assess_page`` once per captured page inside a capture/assess/act loop that
    judges cumulative answerability and proposes the next action.
    """
    publisher = BrowseEventPublisher(event_listener)
    fetcher = html_fetcher or ghost_get_html
    agent_usage = BrowseUsage()
    warnings: list[str] = []
    navigation_outcome = NavigationOutcome.UNKNOWN
    claims: list[EvidenceClaim] = []
    gaps: list[str] = []
    attempted_objectives: list[str] = []
    assessment: EvidenceAssessment | None = None
    url = task.seed_urls[0]
    profile = find_profile(url, task.task_type)
    logger.debug(
        "Browse task {} started for {} (profile={})",
        task.task_id,
        url,
        profile.profile_id if profile else None,
    )
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
    if task.collection.preferred_method == "export" and not (
        profile and profile.supports_export
    ):
        warnings.append(
            "Export collection is not supported for this site; using page collection."
        )
    if task.retain_final_page and not cdp_url:
        warnings.append(
            "Page retention requires an attached browser via cdp_url; the locally "
            "launched browser is closed when the task ends."
        )
    try:
        if html_fetcher is not None:
            logger.debug(
                "Browse task {} fetching seed URL without navigation", task.task_id
            )
            html, usage = await asyncio.to_thread(fetcher, url, cfg)
            retained_tabs = []
            artifacts = []
            # A single non-interactive fetch has no further pages to reach.
            stop_reason = "sufficient"
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
                    navigation_outcome, navigator_usage = await navigate_with_tools(
                        navigator_client, toolset, task, snapshot, profile
                    )
                    agent_usage = _add_usage(agent_usage, navigator_usage)
                    if navigation_outcome is NavigationOutcome.UNKNOWN:
                        warnings.append(
                            "Navigator did not report a verified outcome; collected "
                            "page state may not reflect the requested search."
                        )
                artifacts: list[PageArtifact] = []
                if navigation_outcome in {
                    NavigationOutcome.BLOCKED,
                    NavigationOutcome.TIMEOUT,
                }:
                    stop_reason = "blocked"
                else:
                    await session.settle(tab.tab_id)
                    # A verified empty result set needs one page, never pagination.
                    max_iterations = (
                        1
                        if navigation_outcome is NavigationOutcome.NO_RESULTS
                        else task.limits.max_pages
                    )
                    seen_hashes: set[str] = set()
                    stop_reason = "budget_exhausted"
                    for index in range(max_iterations):
                        artifact = await capture_page(
                            session,
                            tab.tab_id,
                            len(artifacts) + 1,
                            task.limits.max_artifact_chars,
                        )
                        # A repeated page means capture stopped progressing, not
                        # that it finished.
                        if artifact.content_hash in seen_hashes:
                            stop_reason = "no_progress"
                            break
                        seen_hashes.add(artifact.content_hash)
                        artifacts.append(artifact)
                        if extractor_client is not None:
                            (
                                assessment,
                                new_claims,
                                assess_usage,
                            ) = await assess_page(
                                extractor_client, task, artifact, claims, gaps
                            )
                            agent_usage = _add_usage(agent_usage, assess_usage)
                            claims = validated_claims(claims + new_claims, artifacts)
                            gaps = assessment.gaps
                            logger.debug(
                                "Browse task {} assessment after page {}: {}",
                                task.task_id,
                                len(artifacts),
                                assessment.model_dump(mode="json"),
                            )
                            if assessment.answerability == "sufficient":
                                stop_reason = "sufficient"
                                break
                            if assessment.next_action == "stop":
                                stop_reason = "no_next_action"
                                break
                        if index == max_iterations - 1:
                            stop_reason = "budget_exhausted"
                            break
                        if (
                            assessment is not None
                            and assessment.next_action == "investigate"
                            and assessment.objective
                        ):
                            if navigator_client is None:
                                warnings.append(
                                    "Assessor proposed an investigation objective, but "
                                    "no navigator client is configured; stopping."
                                )
                                stop_reason = "no_next_action"
                                break
                            fresh_observation = await toolset.observe()
                            (
                                investigate_outcome,
                                investigate_usage,
                            ) = await navigate_with_tools(
                                navigator_client,
                                toolset,
                                task,
                                fresh_observation,
                                profile,
                                objective=assessment.objective,
                                prior_attempts=list(attempted_objectives),
                            )
                            agent_usage = _add_usage(agent_usage, investigate_usage)
                            attempted_objectives.append(
                                f"{assessment.objective} -> {investigate_outcome.value}"
                            )
                            if investigate_outcome in {
                                NavigationOutcome.BLOCKED,
                                NavigationOutcome.TIMEOUT,
                            }:
                                # Investigation failed, but evidence captured so
                                # far remains valid and must not be discarded.
                                stop_reason = "blocked"
                                warnings.append(
                                    f"Investigation objective reported {investigate_outcome.value}; "
                                    "continuing with evidence captured so far."
                                )
                                break
                            if investigate_outcome is NavigationOutcome.UNKNOWN:
                                warnings.append(
                                    "Navigator did not verifiably complete the "
                                    "investigation objective; continuing with "
                                    "evidence captured so far."
                                )
                            await session.settle(tab.tab_id)
                            continue
                        if not await session.advance_to_next_result_page(tab.tab_id):
                            stop_reason = "no_next_action"
                            break
                html = artifacts[0].text if artifacts else None
                retained_tabs = (
                    [await session.retain_page(tab.tab_id)]
                    if task.retain_final_page and cdp_url
                    else []
                )
                usage = {"input": 0, "output": 0, "total": 0}
    except asyncio.CancelledError:
        logger.debug("Browse task {} cancelled", task.task_id)
        task.status = BrowseTerminalState.CANCELLED
        await publisher.emit(BrowserActionTrace(event="terminal", task_id=task.task_id))
        raise

    normalized_usage = BrowseUsage.model_validate(usage or {})
    if navigation_outcome in {
        NavigationOutcome.BLOCKED,
        NavigationOutcome.TIMEOUT,
    }:
        logger.debug(
            "Browse task {} stopped before collection: navigation reported {}",
            task.task_id,
            navigation_outcome.value,
        )
        task.status = (
            BrowseTerminalState.BLOCKED
            if navigation_outcome is NavigationOutcome.BLOCKED
            else BrowseTerminalState.FAILED
        )
        warnings.append(
            f"Navigation reported {navigation_outcome.value}; no results were "
            "collected and no completeness conclusion is supported."
        )
        blocked_usage = _add_usage(normalized_usage, agent_usage)
        await publisher.emit(BrowserActionTrace(event="terminal", task_id=task.task_id))
        return BrowseResult(
            task_results=[
                BrowseTaskResult(
                    task=task,
                    status=task.status,
                    navigation_outcome=navigation_outcome,
                    site_profile_id=profile.profile_id if profile else None,
                    trace=publisher.events,
                    usage=blocked_usage,
                )
            ],
            warnings=warnings,
            usage=blocked_usage,
        )
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
    logger.debug(
        "Browse task {} captured {} artifact(s); latest chars={} truncated={}",
        task.task_id,
        len(artifacts),
        len(artifacts[-1].text),
        artifacts[-1].truncated,
    )
    answer = ""
    if html_fetcher is not None and extractor_client is not None:
        claims, extractor_usage = await extract_claims(
            extractor_client, artifacts, task
        )
        agent_usage = _add_usage(agent_usage, extractor_usage)
        claims = validated_claims(claims, artifacts)
        logger.debug(
            "Browse task {} validated {} evidence claims", task.task_id, len(claims)
        )
    # Completeness must follow the executor's stop reason, never model narration.
    capture_complete = stop_reason == "sufficient" and not any(
        artifact.truncated for artifact in artifacts
    )
    coverage = CoverageReport(
        pages_captured=len(artifacts),
        stop_reason=stop_reason,
        answerability=assessment.answerability if assessment else "insufficient",
        gaps=gaps,
        artifacts_truncated=any(item.truncated for item in artifacts),
        validated_claims=len(claims),
        constraint_checks=verify_constraints(task.constraints.filters, claims),
    )
    for check in coverage.constraint_checks:
        if not check.verified:
            warnings.append(
                f"Constraint {check.field}={check.value!r} is not shown by any "
                "captured evidence quote."
            )
    logger.debug(
        "Browse task {} coverage {}", task.task_id, coverage.model_dump(mode="json")
    )
    if synthesizer_client is not None:
        answer, cited_claim_ids, synthesizer_usage = await synthesize_answer(
            synthesizer_client, claims, capture_complete, task, coverage
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
            f"Capture stopped ({stop_reason}); results are not exhaustive and no "
            "absence or completeness conclusion is supported."
        )
    normalized_usage = _add_usage(normalized_usage, agent_usage)
    logger.debug(
        "Browse task {} completed with status {} outcome {} and usage {}",
        task.task_id,
        task.status.value,
        navigation_outcome.value,
        normalized_usage.model_dump(),
    )
    result = BrowseTaskResult(
        task=task,
        status=task.status,
        navigation_outcome=navigation_outcome,
        site_profile_id=profile.profile_id if profile else None,
        coverage=coverage,
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
