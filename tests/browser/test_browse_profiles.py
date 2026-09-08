"""Tests for site profiles, navigator outcome gating, and orchestrator branching."""

import json

import pytest

from lexoid.core.browse.profiles import SiteProfile, find_profile
from lexoid.core.browse.schemas import (
    BrowseTask,
    BrowseTerminalState,
    NavigationOutcome,
)
from lexoid.core.browse.tools import BrowserToolset


def test_site_profile_matches_host_and_task_type():
    profile = SiteProfile(
        profile_id="example-search",
        hosts=["example.test"],
        task_types=["search"],
        guidance=["Prefer a field-scoped search builder when one exists."],
    )

    matched = find_profile("https://records.example.test/search", "search", [profile])

    assert matched is profile
    assert matched.supports_export is False
    assert find_profile("https://other.test/search", "search", [profile]) is None
    assert find_profile("https://example.test/x", "capture", [profile]) is None


def test_no_site_is_special_cased_by_default():
    assert find_profile("https://tmsearch.uspto.gov/", "search") is None
    assert find_profile("https://example.test/search", "search") is None


class _OutcomeSession:
    """Session fake exposing only the text used to verify a reported outcome."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def text_content(self, tab_id: str) -> str:
        return self.text


def _toolset(page_text: str) -> BrowserToolset:
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )

    async def emit(_trace) -> None:
        return None

    return BrowserToolset(_OutcomeSession(page_text), task, "tab-1", emit)


@pytest.mark.asyncio
async def test_reported_outcome_requires_visible_evidence():
    toolset = _toolset("Showing 1 - 10 of 42 results")

    rejected = json.loads(
        await toolset.report_outcome("results_ready", "Showing 900 results")
    )

    assert rejected["success"] is False
    assert toolset.outcome is NavigationOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_reported_outcome_accepts_quoted_page_text():
    toolset = _toolset("Showing 1 - 10 of 42 results")

    accepted = json.loads(
        await toolset.report_outcome("results_ready", "1 - 10 of 42 results")
    )

    assert accepted["success"] is True
    assert toolset.outcome is NavigationOutcome.RESULTS_READY


@pytest.mark.asyncio
async def test_blocked_navigation_skips_collection(monkeypatch):
    from lexoid.core.browse import orchestrator

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("collection ran despite blocked navigation")

    monkeypatch.setattr(orchestrator, "capture_page", fail_if_called)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _observation()
    )

    async def _observation():
        return "{}"

    async def navigate(*_args, **_kwargs):
        from lexoid.core.browse.schemas import BrowseUsage

        return NavigationOutcome.BLOCKED, BrowseUsage()

    monkeypatch.setattr(orchestrator, "navigate_with_tools", navigate)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    result = await orchestrator.run_task(task, navigator_client=object())

    task_result = result.task_results[0]
    assert task_result.status is BrowseTerminalState.BLOCKED
    assert task_result.navigation_outcome is NavigationOutcome.BLOCKED
    assert task_result.site_profile_id is None
    assert task_result.artifacts == []


@pytest.mark.asyncio
async def test_investigate_objective_reruns_navigator_and_continues(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import BrowseUsage, EvidenceAssessment, PageArtifact

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

        async def settle(self, tab_id):
            return None

        async def retain_page(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id, target_id="t1", url="https://tmsearch.uspto.gov/"
            )

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    async def _observation():
        return "{}"

    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _observation()
    )

    navigate_calls: list[str | None] = []

    async def navigate(
        client,
        toolset,
        task,
        observation,
        profile=None,
        objective=None,
        prior_attempts=None,
    ):
        navigate_calls.append(objective)
        return NavigationOutcome.RESULTS_READY, BrowseUsage()

    monkeypatch.setattr(orchestrator, "navigate_with_tools", navigate)

    async def fake_capture_page(session, tab_id, index, max_chars):
        return PageArtifact(
            artifact_id=f"artifact-{index}",
            url="https://tmsearch.uspto.gov/",
            tab_id=tab_id,
            content_hash=f"hash-{index}",
            text=f"page {index} text",
        )

    monkeypatch.setattr(orchestrator, "capture_page", fake_capture_page)

    assess_calls: list[str] = []

    async def fake_assess_page(client, task, artifact, prior_claims, prior_gaps):
        assess_calls.append(artifact.artifact_id)
        if len(assess_calls) == 1:
            assessment = EvidenceAssessment(
                answerability="partial",
                gaps=["record detail unverified"],
                next_action="investigate",
                next_action_reason="need to open the first record",
                objective="open the first record and confirm the attorney field",
            )
        else:
            assessment = EvidenceAssessment(answerability="sufficient")
        return assessment, [], BrowseUsage()

    monkeypatch.setattr(orchestrator, "assess_page", fake_assess_page)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    result = await orchestrator.run_task(
        task, navigator_client=object(), extractor_client=object()
    )

    task_result = result.task_results[0]
    assert assess_calls == ["artifact-1", "artifact-2"]
    assert navigate_calls == [
        None,
        "open the first record and confirm the attorney field",
    ]
    assert task_result.coverage.stop_reason == "sufficient"
    assert task_result.status is BrowseTerminalState.COMPLETED
