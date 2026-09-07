"""Tests for generic task constraints, site profiles, and outcome gating."""

import json

import pytest

from lexoid.core.browse.agents import validate_planned_task
from lexoid.core.browse.profiles import SiteProfile, find_profile
from lexoid.core.browse.schemas import (
    BrowseLimits,
    BrowseTask,
    BrowseTerminalState,
    NavigationOutcome,
)
from lexoid.core.browse.tools import BrowserToolset

QUERY = (
    "Go to https://tmsearch.uspto.gov/ and retrieve all cases related to "
    "Arash Samadani as attorney"
)


def test_planner_preserves_user_filters():
    task = validate_planned_task(
        QUERY,
        {
            "seed_urls": ["https://tmsearch.uspto.gov/"],
            "subject": "Arash Samadani",
            "allowed_domains": ["tmsearch.uspto.gov"],
            "constraints": {
                "filters": [
                    {
                        "field": "attorney",
                        "operator": "unspecified",
                        "value": "Arash Samadani",
                    }
                ],
                "coverage": "all_matches",
            },
        },
        BrowseLimits(),
    )

    assert task.constraints.filters[0].field == "attorney"
    assert task.constraints.coverage == "all_matches"


def test_planner_rejects_invented_filter_value():
    payload = {
        "seed_urls": ["https://tmsearch.uspto.gov/"],
        "subject": "Arash Samadani",
        "allowed_domains": ["tmsearch.uspto.gov"],
        "constraints": {
            "filters": [{"field": "owner", "value": "Unrelated Person"}],
        },
    }

    with pytest.raises(ValueError, match="invented a filter value"):
        validate_planned_task(QUERY, payload, BrowseLimits())


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
