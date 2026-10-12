"""Single-task browse orchestration with deterministic evidence handling."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any

from lexoid.core.browse.agents import (
    assess_page,
    extract_claims,
    navigate_with_tools,
    synthesize_answer,
)
from lexoid.core.browse.collector import capture_page
from lexoid.core.browse.events import BrowseEventListener, BrowseEventPublisher
from lexoid.core.browse.evidence import validated_claims, verify_constraints
from lexoid.core.browse.model_provider import ChatClient
from lexoid.core.browse.policy import is_allowed_url
from lexoid.core.browse.profiles import find_profile
from lexoid.core.browse.schemas import (
    BrowserActionTrace,
    BrowseResult,
    BrowseTask,
    BrowseTaskResult,
    BrowseTerminalState,
    BrowseUsage,
    CandidateAssessment,
    CoverageReport,
    EvidenceAssessment,
    EvidenceClaim,
    NavigationOutcome,
    PageArtifact,
    PlanOutcomeRecord,
    SynthesisAssessment,
)
from lexoid.core.browse.session import GhostBrowserSession
from lexoid.core.browse.tools import BrowserToolset
from lexoid.core.ghost import GhostConfig, ghost_get_html
from loguru import logger

HtmlFetcher = Callable[[str, GhostConfig], tuple[str | None, dict[str, int]]]


def _add_usage(left: BrowseUsage, right: BrowseUsage) -> BrowseUsage:
    """Combine usage across model roles for per-run cost measurement."""
    return BrowseUsage(
        input=left.input + right.input,
        output=left.output + right.output,
        total=left.total + right.total,
    )


def _validate_assessment(
    assessment: EvidenceAssessment,
    task: BrowseTask,
    claims: list[EvidenceClaim],
    rejected_claim_count: int,
) -> tuple[EvidenceAssessment, list[str]]:
    valid_claim_ids = {claim.claim_id for claim in claims}
    valid_source_urls = {claim.source_url for claim in claims}
    validation_warnings: list[str] = []
    candidates: list[CandidateAssessment] = []
    gaps = list(assessment.gaps)

    def normalized_key(value: str) -> str:
        return " ".join(value.split()).casefold()

    for candidate in assessment.candidates:
        if candidate.source_url not in valid_source_urls:
            validation_warnings.append(
                f"Dropped candidate assessment with no validated claim from {candidate.source_url}."
            )
            continue
        hard_constraints = []
        for item in candidate.hard_constraints:
            claim_ids = [
                claim_id for claim_id in item.claim_ids if claim_id in valid_claim_ids
            ]
            if len(claim_ids) != len(item.claim_ids):
                validation_warnings.append(
                    f"Dropped invalid claim references for candidate filter {item.field}."
                )
            status = item.status
            if status == "supported" and not claim_ids:
                status = "missing"
            hard_constraints.append(
                item.model_copy(update={"status": status, "claim_ids": claim_ids})
            )
        criteria_support = []
        for item in candidate.criteria_support:
            claim_ids = [
                claim_id for claim_id in item.claim_ids if claim_id in valid_claim_ids
            ]
            if len(claim_ids) != len(item.claim_ids):
                validation_warnings.append(
                    f"Dropped invalid claim references for criterion {item.criterion}."
                )
            status = item.assessment
            if status in {"supported", "mixed"} and not claim_ids:
                status = "unsupported"
            criteria_support.append(
                item.model_copy(update={"assessment": status, "claim_ids": claim_ids})
            )
        candidates.append(
            candidate.model_copy(
                update={
                    "hard_constraints": hard_constraints,
                    "criteria_support": criteria_support,
                }
            )
        )

    answerability = assessment.answerability
    next_action = assessment.next_action
    next_action_reason = assessment.next_action_reason
    if rejected_claim_count and answerability == "sufficient":
        answerability = "partial"
    if rejected_claim_count:
        validation_warnings.append(
            f"Rejected {rejected_claim_count} claim(s) that failed exact-quote validation."
        )
    needs_candidate_evidence = bool(
        task.constraints.filters
        or task.constraints.evaluation_criteria
        or task.constraints.max_records
    )
    if answerability == "sufficient" and needs_candidate_evidence:
        expected_filters = {
            normalized_key(item.field) for item in task.constraints.filters
        }
        expected_criteria = {
            normalized_key(item) for item in task.constraints.evaluation_criteria
        }
        qualifying_candidates = 0
        for candidate in candidates:
            constraints_by_field = {
                normalized_key(item.field): item for item in candidate.hard_constraints
            }
            criteria_by_name = {
                normalized_key(item.criterion): item
                for item in candidate.criteria_support
            }
            has_constraints = all(
                field in constraints_by_field
                and constraints_by_field[field].status == "supported"
                and bool(constraints_by_field[field].claim_ids)
                for field in expected_filters
            )
            has_criteria = all(
                criterion in criteria_by_name
                and criteria_by_name[criterion].assessment == "supported"
                and bool(criteria_by_name[criterion].claim_ids)
                for criterion in expected_criteria
            )
            if has_constraints and has_criteria:
                qualifying_candidates += 1
        required_candidates = task.constraints.max_records or 1
        if qualifying_candidates < required_candidates:
            gaps.append(
                f"Only {qualifying_candidates} candidate(s) have claim-supported evidence for the requested filters and criteria; {required_candidates} are needed."
            )
            if answerability == "sufficient":
                answerability = "partial"
            if next_action == "stop":
                next_action = "paginate"
                next_action_reason = (
                    "Continue to another reachable result page to find enough "
                    "candidates with claim-supported filters and criteria."
                )
    return assessment.model_copy(
        update={
            "answerability": answerability,
            "next_action": next_action,
            "next_action_reason": next_action_reason,
            "gaps": list(dict.fromkeys(gaps))[:20],
            "candidates": candidates,
        }
    ), validation_warnings


def _render_assessments(
    answer: str,
    assessments: list[SynthesisAssessment],
    claims: list[EvidenceClaim],
) -> str:
    if not assessments:
        return answer
    section = ["### Assessment"]
    claims_by_id = {claim.claim_id: claim for claim in claims}
    for item in assessments:
        citations = [
            f'"{claims_by_id[claim_id].quote}" - {claims_by_id[claim_id].source_url}'
            for claim_id in item.based_on_claim_ids
            if claim_id in claims_by_id
        ]
        section.append(f"- {item.statement} ({'; '.join(citations)})")
    section_text = "\n".join(section)
    if "### Coverage & Gaps" in answer:
        body, coverage = answer.split("### Coverage & Gaps", maxsplit=1)
        return f"{body.rstrip()}\n\n{section_text}\n\n### Coverage & Gaps{coverage}"
    return f"{answer.rstrip()}\n\n{section_text}".strip()


def _validate_synthesis_assessments(
    assessments: list[SynthesisAssessment], claims: list[EvidenceClaim]
) -> tuple[list[SynthesisAssessment], list[SynthesisAssessment]]:
    valid_claim_ids = {claim.claim_id for claim in claims}
    accepted = [
        item
        for item in assessments
        if item.based_on_claim_ids
        and set(item.based_on_claim_ids).issubset(valid_claim_ids)
    ]
    rejected = [item for item in assessments if item not in accepted]
    return accepted, rejected


async def _blocked_result(
    task: BrowseTask,
    publisher: BrowseEventPublisher,
    reason: str,
    warning: str,
    warnings: list[str] | None = None,
) -> BrowseResult:
    """Return a terminal BLOCKED task result with a recorded plan outcome."""
    task.status = BrowseTerminalState.BLOCKED
    plan_outcome = PlanOutcomeRecord(
        task_id=task.task_id,
        intent=task.strategy.intent or task.subject,
        assumptions=task.strategy.assumptions,
        navigation_guidance=task.strategy.navigation_guidance,
        coverage_requested=task.constraints.coverage,
        stop_reason="blocked",
        answerability="insufficient",
        unresolved_gaps=[reason],
        validated_claims_count=0,
        pages_captured=0,
    )
    await publisher.emit(
        BrowserActionTrace(
            event="terminal",
            task_id=task.task_id,
            metadata={"plan_outcome": plan_outcome.model_dump(mode="json")},
        )
    )
    combined_warnings = list(warnings or [])
    if warning not in combined_warnings:
        combined_warnings.append(warning)
    return BrowseResult(
        task_results=[
            BrowseTaskResult(
                task=task,
                status=task.status,
                trace=publisher.events,
                plan_outcome=plan_outcome,
            )
        ],
        warnings=combined_warnings,
    )


async def run_task(
    task: BrowseTask,
    *,
    cdp_url: str | None = None,
    headless: bool = True,
    event_listener: BrowseEventListener | None = None,
    html_fetcher: HtmlFetcher | None = None,
    navigator_client: ChatClient | None = None,
    navigator_options: dict[str, Any] | None = None,
    assessor_client: ChatClient | None = None,
    assessor_options: dict[str, Any] | None = None,
    extractor_client: ChatClient | None = None,
    extractor_options: dict[str, Any] | None = None,
    synthesizer_client: ChatClient | None = None,
    synthesizer_options: dict[str, Any] | None = None,
) -> BrowseResult:
    """Capture one allowlisted page and return a typed, grounded task result.

    ``extractor_client`` drives the non-interactive ``html_fetcher`` path's
    end-of-capture ``extract_claims`` call. In the live browser-session path,
    ``assessor_client`` (falling back to ``extractor_client``) drives
    ``assess_page`` once per captured page inside a capture/assess/act loop that
    judges cumulative answerability and proposes the next action.
    """
    publisher = BrowseEventPublisher(event_listener)
    await publisher.emit(
        BrowserActionTrace(
            event="plan",
            task_id=task.task_id,
            metadata={
                "subject": task.subject,
                "intent": task.strategy.intent,
                "approach": task.strategy.approach,
                "navigation_guidance": task.strategy.navigation_guidance,
                "assumptions": task.strategy.assumptions,
                "seed_urls": task.seed_urls,
                "inferred_seeds": [s.model_dump() for s in task.inferred_seeds],
                "allowed_domains": task.allowed_domains,
                "requested_facts": task.requested_facts,
                "completion_criteria": task.completion_criteria,
                "filters": [
                    {"field": f.field, "operator": f.operator, "value": f.value}
                    for f in task.constraints.filters
                ],
                "evaluation_criteria": task.constraints.evaluation_criteria,
                "coverage": task.constraints.coverage,
            },
        )
    )
    fetcher = html_fetcher or ghost_get_html
    agent_usage = BrowseUsage()
    effective_assessor_client = assessor_client or extractor_client
    effective_assessor_options = (
        assessor_options if assessor_options is not None else extractor_options
    )
    warnings: list[str] = list(task.warnings)
    navigation_outcome = NavigationOutcome.UNKNOWN
    claims: list[EvidenceClaim] = []
    gaps: list[str] = []
    attempted_objectives: list[str] = []
    candidate_assessments: list[CandidateAssessment] = []
    accepted_assessments: list[SynthesisAssessment] = []
    assessment: EvidenceAssessment | None = None
    url = task.seed_urls[0] if task.seed_urls else task.inferred_seeds[0].url
    if not task.seed_urls and task.inferred_seeds:
        warnings.append(
            f"Starting seed URL was inferred from {task.inferred_seeds[0].source_text!r} "
            "(inferred, not verified)."
        )
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
        return await _blocked_result(
            task,
            publisher,
            "Seed URL outside HTTPS allowlist",
            "Seed URL is outside the HTTPS task allowlist.",
            warnings=warnings,
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
                if not is_allowed_url(tab.url, task.allowed_domains):
                    logger.debug(
                        "Browse task {} blocked: initial landing URL {} is outside allowlist",
                        task.task_id,
                        tab.url,
                    )
                    await session.close_tab(tab.tab_id)
                    return await _blocked_result(
                        task,
                        publisher,
                        "Initial landing URL outside HTTPS allowlist",
                        "Initial navigation landed outside the HTTPS task allowlist.",
                        warnings=warnings,
                    )
                toolset = BrowserToolset(session, task, tab.tab_id, publisher.emit)
                snapshot = await toolset.observe()
                logger.debug(
                    "Browse task {} captured initial observation on tab {}",
                    task.task_id,
                    tab.tab_id,
                )
                if navigator_client is not None and not toolset.is_quarantined:
                    navigation_outcome, navigator_usage = await navigate_with_tools(
                        navigator_client,
                        toolset,
                        task,
                        snapshot,
                        profile,
                        role_options=navigator_options,
                    )
                    agent_usage = _add_usage(agent_usage, navigator_usage)
                    if navigation_outcome is NavigationOutcome.UNKNOWN:
                        warnings.append(
                            "Navigator did not report a verified outcome; collected "
                            "page state may not reflect the requested search."
                        )
                if toolset.is_quarantined:
                    navigation_outcome = NavigationOutcome.BLOCKED
                    current_tab = None
                else:
                    current_tab = await session.tab(toolset.tab_id)
                page_reached = current_tab is not None and (
                    current_tab.url != url or toolset.successful_action_count > 0
                )
                navigator_budget_exhausted = (
                    toolset.step_limit_reached and not toolset.is_quarantined
                )
                artifacts: list[PageArtifact] = []
                if toolset.is_quarantined:
                    stop_reason = "blocked"
                    warnings.append(
                        "Active tab was quarantined after an allowlist verification failure."
                    )
                elif (
                    navigation_outcome
                    in {
                        NavigationOutcome.BLOCKED,
                        NavigationOutcome.TIMEOUT,
                    }
                    and not page_reached
                    and not navigator_budget_exhausted
                ):
                    stop_reason = "blocked"
                else:
                    await session.settle(toolset.tab_id)
                    if (
                        navigation_outcome
                        in {
                            NavigationOutcome.BLOCKED,
                            NavigationOutcome.TIMEOUT,
                        }
                        and not navigator_budget_exhausted
                    ):
                        # Navigation self-reported blocked/timeout, but the page was
                        # reached; capture the reached page as evidence rather than
                        # discarding it based solely on model self-report.
                        max_iterations = 1
                        stop_reason = "blocked"
                        warnings.append(
                            f"Navigation reported {navigation_outcome.value}, but reached "
                            "page was captured for evidence assessment."
                        )
                    elif navigation_outcome is NavigationOutcome.NO_RESULTS:
                        # A verified empty result set needs one page, never pagination.
                        max_iterations = 1
                        stop_reason = "budget_exhausted"
                    else:
                        max_iterations = task.limits.max_pages
                        stop_reason = "budget_exhausted"

                    seen_hashes: set[str] = set()
                    for index in range(max_iterations):
                        current_tab = await session.tab(toolset.tab_id)
                        if not is_allowed_url(current_tab.url, task.allowed_domains):
                            logger.debug(
                                "Browse task {} capture blocked: tab {} URL {} outside allowlist",
                                task.task_id,
                                toolset.tab_id,
                                current_tab.url,
                            )
                            await toolset.quarantine()
                            navigation_outcome = NavigationOutcome.BLOCKED
                            stop_reason = "blocked"
                            warnings.append(
                                "Page capture skipped: current tab URL is outside the HTTPS task allowlist."
                            )
                            break
                        artifact = await capture_page(
                            session,
                            toolset.tab_id,
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
                        if effective_assessor_client is not None:
                            (
                                assessment,
                                new_claims,
                                assess_usage,
                            ) = await assess_page(
                                effective_assessor_client,
                                task,
                                artifact,
                                claims,
                                gaps,
                                prior_context={
                                    "captured_urls": [item.url for item in artifacts],
                                    "attempted_objectives": list(attempted_objectives),
                                },
                                role_options=effective_assessor_options,
                            )
                            agent_usage = _add_usage(agent_usage, assess_usage)
                            validated_new_claims = validated_claims(
                                new_claims, artifacts
                            )
                            claims = validated_claims(claims + new_claims, artifacts)
                            assessment, assessment_warnings = _validate_assessment(
                                assessment,
                                task,
                                claims,
                                len(new_claims) - len(validated_new_claims),
                            )
                            warnings.extend(assessment_warnings)
                            candidate_assessments = assessment.candidates
                            gaps = assessment.gaps
                            await publisher.emit(
                                BrowserActionTrace(
                                    event="decision",
                                    task_id=task.task_id,
                                    tab_id=artifact.tab_id,
                                    metadata={
                                        "role": "assessor",
                                        "question": "Is the evidence sufficient, what facts remain missing, and which candidate evidence supports each criterion?",
                                        "state_ref": {
                                            "artifact_id": artifact.artifact_id,
                                            "source_url": artifact.url,
                                        },
                                        "options": {
                                            "answerability": [
                                                "sufficient",
                                                "partial",
                                                "insufficient",
                                            ],
                                            "next_action": [
                                                "paginate",
                                                "investigate",
                                                "stop",
                                            ],
                                        },
                                        "selected": assessment.model_dump(mode="json"),
                                    },
                                )
                            )
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
                            if stop_reason != "blocked":
                                stop_reason = "budget_exhausted"
                            break
                        if (
                            assessment is not None
                            and assessment.next_action == "investigate"
                            and assessment.objective
                            and toolset.remaining_task_actions > 0
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
                                gaps=list(gaps),
                                reason=assessment.next_action_reason,
                                role_options=navigator_options,
                            )
                            agent_usage = _add_usage(agent_usage, investigate_usage)
                            attempted_objectives.append(
                                f"{assessment.objective} -> {investigate_outcome.value}"
                            )
                            investigation_budget_exhausted = (
                                toolset.step_limit_reached
                                and not toolset.is_quarantined
                            )
                            if toolset.is_quarantined or (
                                investigate_outcome
                                in {
                                    NavigationOutcome.BLOCKED,
                                    NavigationOutcome.TIMEOUT,
                                }
                                and not investigation_budget_exhausted
                            ):
                                # Investigation failed, but evidence captured so
                                # far remains valid and must not be discarded.
                                stop_reason = "blocked"
                                warnings.append(
                                    f"Investigation objective reported {investigate_outcome.value}; "
                                    "continuing with evidence captured so far."
                                )
                                break
                            if (
                                investigate_outcome
                                is NavigationOutcome.BUDGET_EXHAUSTED
                                and not toolset.is_quarantined
                            ):
                                investigation_budget_exhausted = True
                            if investigate_outcome is NavigationOutcome.UNKNOWN:
                                warnings.append(
                                    "Navigator did not verifiably complete the "
                                    "investigation objective; continuing with "
                                    "evidence captured so far."
                                )
                            if investigation_budget_exhausted:
                                warnings.append(
                                    "Investigation used its navigator action budget; "
                                    "trying deterministic pagination."
                                )
                            else:
                                await session.settle(toolset.tab_id)
                                continue
                        if not await session.advance_to_next_result_page(
                            toolset.tab_id
                        ):
                            stop_reason = "no_next_action"
                            break
                html = artifacts[0].text if artifacts else None
                retained_tabs = (
                    [await session.retain_page(toolset.tab_id)]
                    if task.retain_final_page and cdp_url and not toolset.is_quarantined
                    else []
                )
                usage = {"input": 0, "output": 0, "total": 0}
    except asyncio.CancelledError:
        logger.debug("Browse task {} cancelled", task.task_id)
        task.status = BrowseTerminalState.CANCELLED
        await publisher.emit(BrowserActionTrace(event="terminal", task_id=task.task_id))
        raise

    normalized_usage = BrowseUsage.model_validate(usage or {})
    if (
        navigation_outcome
        in {
            NavigationOutcome.BLOCKED,
            NavigationOutcome.TIMEOUT,
        }
        and not artifacts
    ):
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
        plan_outcome = PlanOutcomeRecord(
            task_id=task.task_id,
            intent=task.strategy.intent or task.subject,
            assumptions=task.strategy.assumptions,
            navigation_guidance=task.strategy.navigation_guidance,
            coverage_requested=task.constraints.coverage,
            stop_reason="blocked",
            answerability="insufficient",
            unresolved_gaps=[f"Navigation reported {navigation_outcome.value}"],
            validated_claims_count=0,
            pages_captured=0,
        )
        await publisher.emit(
            BrowserActionTrace(
                event="terminal",
                task_id=task.task_id,
                metadata={"plan_outcome": plan_outcome.model_dump(mode="json")},
            )
        )
        return BrowseResult(
            task_results=[
                BrowseTaskResult(
                    task=task,
                    status=task.status,
                    navigation_outcome=navigation_outcome,
                    site_profile_id=profile.profile_id if profile else None,
                    trace=publisher.events,
                    usage=blocked_usage,
                    plan_outcome=plan_outcome,
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
        plan_outcome = PlanOutcomeRecord(
            task_id=task.task_id,
            intent=task.strategy.intent or task.subject,
            assumptions=task.strategy.assumptions,
            navigation_guidance=task.strategy.navigation_guidance,
            coverage_requested=task.constraints.coverage,
            stop_reason="blocked",
            answerability="insufficient",
            unresolved_gaps=["Page capture failed to return HTML"],
            validated_claims_count=0,
            pages_captured=0,
        )
        result = BrowseTaskResult(
            task=task,
            status=task.status,
            usage=normalized_usage,
            plan_outcome=plan_outcome,
        )
        await publisher.emit(
            BrowserActionTrace(
                event="terminal",
                task_id=task.task_id,
                metadata={"plan_outcome": plan_outcome.model_dump(mode="json")},
            )
        )
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
            extractor_client, artifacts, task, role_options=extractor_options
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
        if not check.value_present:
            warnings.append(
                f"Constraint {check.field}={check.value!r} is not shown by any "
                "captured evidence quote."
            )
    logger.debug(
        "Browse task {} coverage {}", task.task_id, coverage.model_dump(mode="json")
    )
    if synthesizer_client is not None:
        (
            answer,
            cited_claim_ids,
            proposed_assessments,
            synthesizer_usage,
        ) = await synthesize_answer(
            synthesizer_client,
            claims,
            capture_complete,
            task,
            coverage,
            candidate_assessments=candidate_assessments,
            role_options=synthesizer_options,
        )
        agent_usage = _add_usage(agent_usage, synthesizer_usage)
        valid_claim_ids = {claim.claim_id for claim in claims}
        if not set(cited_claim_ids).issubset(valid_claim_ids):
            raise ValueError("synthesizer cited an unknown evidence claim")
        if answer and not cited_claim_ids:
            warnings.append("Answer is not supported by validated evidence claims.")
        accepted_assessments, rejected_assessments = _validate_synthesis_assessments(
            proposed_assessments, claims
        )
        for item in rejected_assessments:
            warnings.append(f"Dropped unsupported assessment: {item.statement[:160]}")
        valid_claim_ids = {claim.claim_id for claim in claims}
        await publisher.emit(
            BrowserActionTrace(
                event="decision",
                task_id=task.task_id,
                metadata={
                    "role": "synthesizer",
                    "question": "Which conclusions are directly stated facts and which are evidence-based assessments?",
                    "state_ref": {"claim_ids": sorted(valid_claim_ids)},
                    "options": {"claim_ids": sorted(valid_claim_ids)},
                    "selected": {
                        "claim_ids": cited_claim_ids,
                        "assessments": [
                            item.model_dump(mode="json")
                            for item in accepted_assessments
                        ],
                    },
                },
            )
        )
        answer = _render_assessments(answer, accepted_assessments, claims)
    if capture_complete:
        task.status = BrowseTerminalState.COMPLETED
    else:
        task.status = (
            BrowseTerminalState.BLOCKED
            if not claims and navigation_outcome is NavigationOutcome.BLOCKED
            else BrowseTerminalState.LIMIT_REACHED
        )
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
    plan_outcome = PlanOutcomeRecord(
        task_id=task.task_id,
        intent=task.strategy.intent or task.subject,
        assumptions=task.strategy.assumptions,
        navigation_guidance=task.strategy.navigation_guidance,
        coverage_requested=task.constraints.coverage,
        stop_reason=stop_reason,
        answerability=coverage.answerability,
        unresolved_gaps=coverage.gaps,
        validated_claims_count=len(claims),
        pages_captured=len(artifacts),
    )
    result = BrowseTaskResult(
        task=task,
        status=task.status,
        navigation_outcome=navigation_outcome,
        site_profile_id=profile.profile_id if profile else None,
        coverage=coverage,
        artifacts=artifacts,
        claims=claims,
        candidate_assessments=candidate_assessments,
        assessments=accepted_assessments,
        trace=publisher.events,
        retained_tabs=retained_tabs,
        usage=normalized_usage,
        plan_outcome=plan_outcome,
    )
    await publisher.emit(BrowserActionTrace(event="artifact", task_id=task.task_id))
    await publisher.emit(
        BrowserActionTrace(
            event="terminal",
            task_id=task.task_id,
            metadata={"plan_outcome": plan_outcome.model_dump(mode="json")},
        )
    )
    result.trace = publisher.events
    return BrowseResult(
        answer=answer,
        task_results=[result],
        warnings=warnings,
        usage=normalized_usage,
    )
