"""Tests for site profiles, navigator outcome gating, and orchestrator branching."""

import json
from typing import Any, cast

import pytest
from lexoid.core.browse.profiles import SiteProfile, find_profile
from lexoid.core.browse.schemas import (
    BrowseTask,
    BrowseTerminalState,
    NavigationOutcome,
    OpenTab,
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
    assert matched is not None
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

    async def list_tabs(self) -> list[OpenTab]:
        from lexoid.core.browse.schemas import OpenTab

        return [OpenTab(tab_id="tab-1", target_id="t1", url="https://example.test/")]

    async def tab(self, tab_id: str) -> OpenTab:
        from lexoid.core.browse.schemas import OpenTab

        return OpenTab(tab_id=tab_id, target_id="t1", url="https://example.test/")


def _toolset(page_text: str) -> BrowserToolset:
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )

    async def emit(_trace) -> None:
        return None

    return BrowserToolset(cast(Any, _OutcomeSession(page_text)), task, "tab-1", emit)


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
async def test_read_text_returns_bounded_rendered_text():
    emitted = []

    async def emit(trace):
        emitted.append(trace)

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )
    long_text = "Case #101: Pending approval.\n" * 200
    toolset = BrowserToolset(cast(Any, _OutcomeSession(long_text)), task, "tab-1", emit)

    raw = await toolset.read_text(max_chars=500)
    data = json.loads(raw)

    assert len(data["text"]) == 500
    assert data["total_chars"] == len(long_text)
    assert data["truncated"] is True
    assert toolset.action_count == 0
    assert toolset.successful_action_count == 0
    assert emitted[-1].event == "observation"
    assert emitted[-1].metadata["action"] == "read_text"


@pytest.mark.asyncio
async def test_read_text_available_in_toolset_functions():
    toolset = _toolset("some text")
    tool_names = [func.__name__ for func in toolset.functions()]
    assert "read_text" in tool_names
    assert "observe" in tool_names
    assert "list_tabs" in tool_names
    assert "switch_tab" in tool_names


@pytest.mark.asyncio
async def test_scroll_tool_supports_optional_ref():
    emitted = []

    async def emit(trace):
        emitted.append(trace)

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )

    class _ScrollSession:
        async def snapshot(self, tab_id: str):
            from lexoid.core.browse.schemas import BrowserSnapshot

            return BrowserSnapshot(
                snapshot_id="s1",
                tab_id=tab_id,
                page_revision=0,
                url="https://example.test/",
                viewport_width=1280,
                viewport_height=720,
                scroll_x=0,
                scroll_y=0,
                content_hash="h1",
            )

        async def execute(self, action):
            from lexoid.core.browse.schemas import BrowserActionResult

            return BrowserActionResult(success=True, outcome="ok")

    toolset = BrowserToolset(cast(Any, _ScrollSession()), task, "tab-1", emit)
    await toolset.scroll(direction="down", ref="e1")
    assert toolset.action_count == 1
    assert toolset.successful_action_count == 1
    action_trace = [e for e in emitted if e.event == "action"][-1]
    assert action_trace.action is not None
    assert action_trace.action.kind == "scroll"
    assert action_trace.action.ref == "e1"
    assert action_trace.action.text == "down"


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

        async def tab(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id,
                target_id="t1",
                url="https://tmsearch.uspto.gov/",
            )

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

        async def tab(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id,
                target_id="t1",
                url="https://tmsearch.uspto.gov/",
            )

        async def settle(self, tab_id):
            return None

        async def retain_page(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id, target_id="t1", url="https://tmsearch.uspto.gov/"
            )

        async def advance_to_next_result_page(self, tab_id):
            return False

        async def list_tabs(self):
            return [await self.tab("tab-1")]

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    async def _observation():
        return "{}"

    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _observation()
    )

    navigate_calls: list[tuple[str | None, list[str] | None, str | None]] = []

    async def navigate(
        client,
        toolset,
        task,
        observation,
        profile=None,
        objective=None,
        prior_attempts=None,
        gaps=None,
        reason=None,
        **kwargs,
    ):
        navigate_calls.append((objective, gaps, reason))
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

    async def fake_assess_page(
        client, task, artifact, prior_claims, prior_gaps, **kwargs
    ):
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
        (None, None, None),
        (
            "open the first record and confirm the attorney field",
            ["record detail unverified"],
            "need to open the first record",
        ),
    ]
    assert task_result.coverage.stop_reason == "sufficient"
    assert task_result.status is BrowseTerminalState.COMPLETED


@pytest.mark.asyncio
async def test_orchestrator_captures_and_paginates_on_switched_active_tab(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import (
        BrowseUsage,
        EvidenceAssessment,
        OpenTab,
        PageArtifact,
    )

    captured_tab_ids: list[str] = []
    advanced_tab_ids: list[str] = []
    settled_tab_ids: list[str] = []
    retained_tab_ids: list[str] = []

    class _MultiTabSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-seed", target_id="t1", url=url)

        async def tab(self, tab_id):
            return OpenTab(
                tab_id=tab_id, target_id=tab_id, url=f"https://example.com/{tab_id}"
            )

        async def list_tabs(self):
            return [
                OpenTab(
                    tab_id="tab-seed", target_id="t1", url="https://example.com/search"
                ),
                OpenTab(
                    tab_id="tab-listing",
                    target_id="t2",
                    url="https://example.com/listing/1",
                ),
            ]

        async def settle(self, tab_id):
            settled_tab_ids.append(tab_id)

        async def retain_page(self, tab_id):
            retained_tab_ids.append(tab_id)
            return OpenTab(
                tab_id=tab_id, target_id=tab_id, url=f"https://example.com/{tab_id}"
            )

        async def advance_to_next_result_page(self, tab_id):
            advanced_tab_ids.append(tab_id)
            return False

    monkeypatch.setattr(
        orchestrator, "GhostBrowserSession", lambda cfg: _MultiTabSession()
    )
    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _dummy_obs()
    )

    async def _dummy_obs():
        return "{}"

    async def navigate_and_switch(client, toolset, task, obs, profile=None, **kwargs):
        toolset._tab_id = "tab-listing"
        toolset.successful_action_count = 1
        return NavigationOutcome.RESULTS_READY, BrowseUsage()

    monkeypatch.setattr(orchestrator, "navigate_with_tools", navigate_and_switch)

    async def fake_capture(session, tab_id, index, max_chars):
        captured_tab_ids.append(tab_id)
        return PageArtifact(
            artifact_id=f"art-{index}",
            url=f"https://example.com/{tab_id}",
            tab_id=tab_id,
            content_hash=f"hash-{index}",
            text="evidence text",
        )

    monkeypatch.setattr(orchestrator, "capture_page", fake_capture)

    async def fake_assess(client, task, artifact, prior_claims, prior_gaps, **kwargs):
        return (
            EvidenceAssessment(answerability="partial", next_action="paginate"),
            [],
            BrowseUsage(),
        )

    monkeypatch.setattr(orchestrator, "assess_page", fake_assess)

    task = BrowseTask(
        seed_urls=["https://example.com/search"],
        subject="test",
        allowed_domains=["example.com"],
        retain_final_page=True,
    )

    result = await orchestrator.run_task(
        task,
        cdp_url="http://localhost:9222",
        navigator_client=object(),
        extractor_client=object(),
    )

    assert captured_tab_ids == ["tab-listing"]
    assert advanced_tab_ids == ["tab-listing"]
    assert settled_tab_ids == ["tab-listing"]
    assert retained_tab_ids == ["tab-listing"]
    assert result.task_results[0].status is BrowseTerminalState.LIMIT_REACHED
