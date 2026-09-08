"""Tests for the initial typed single-task browse executor."""

import os

import pytest

from lexoid.api import browse
from lexoid.core.browse.evidence import validated_claims
from lexoid.core.browse.schemas import (
    BrowseTask,
    BrowseTerminalState,
    EvidenceClaim,
    PageArtifact,
)


@pytest.mark.asyncio
async def test_browse_requires_explicit_https_url():
    with pytest.raises(ValueError, match="clarification_needed"):
        await browse("search trademark records")


@pytest.mark.asyncio
async def test_browse_rejects_unsupported_model_before_capture():
    with pytest.raises(ValueError, match="model_unsupported"):
        await browse("https://tmsearch.uspto.gov/", navigator_model="unknown-model")


@pytest.mark.asyncio
async def test_prebuilt_task_bypasses_query_planning(monkeypatch):
    from lexoid.core.browse import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "ghost_get_html",
        lambda url, cfg: (
            "<html>captured evidence</html>",
            {"input": 1, "output": 2, "total": 3},
        ),
    )
    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    result = await orchestrator.run_task(task, html_fetcher=orchestrator.ghost_get_html)

    task_result = result.task_results[0]
    assert task_result.status is BrowseTerminalState.COMPLETED
    assert task_result.artifacts[0].text == "<html>captured evidence</html>"
    assert result.usage.total == 3


@pytest.mark.asyncio
async def test_run_task_passes_headless_setting_to_browser_config():
    from lexoid.core.browse import orchestrator

    seen_configs = []

    def fetcher(url, config):
        seen_configs.append(config)
        return "<html>captured evidence</html>", {"input": 0, "output": 0, "total": 0}

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    await orchestrator.run_task(task, headless=False, html_fetcher=fetcher)

    assert seen_configs[0].headless is False


def test_evidence_claim_requires_exact_artifact_quote():
    artifact = PageArtifact(
        artifact_id="artifact-1",
        url="https://tmsearch.uspto.gov/",
        tab_id="tab-1",
        content_hash="hash",
        text="Arash Samadani appears in the result.",
    )
    supported = EvidenceClaim(
        claim_id="claim-1",
        text="The result names Arash Samadani.",
        quote="Arash Samadani appears",
        artifact_id="artifact-1",
        source_url="https://tmsearch.uspto.gov/",
    )
    unsupported = supported.model_copy(
        update={"claim_id": "claim-2", "quote": "invented"}
    )

    assert validated_claims([supported, unsupported], [artifact]) == [supported]


def test_public_schemas_produce_json_schema():
    schema = BrowseTask.model_json_schema()

    assert schema["properties"]["seed_urls"]["type"] == "array"
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_browse_live_cdp_captures_and_retains_uspto_page():
    """Exercise the high-level API against an explicitly attached browser."""
    if not os.getenv("RUN_BROWSE_LIVE_TESTS"):
        pytest.skip("RUN_BROWSE_LIVE_TESTS is not enabled")
    cdp_url = os.getenv("LEXOID_CDP_URL")
    if not cdp_url:
        pytest.skip("LEXOID_CDP_URL is required for the live browse test")

    result = await browse(
        "Go to https://tmsearch.uspto.gov/ and retrieve all cases related for Arash Samadani",
        cdp_url=cdp_url,
    )

    task_result = result.task_results[0]
    assert task_result.status is BrowseTerminalState.COMPLETED
    assert task_result.artifacts
    assert task_result.artifacts[0].url.startswith("https://tmsearch.uspto.gov/")
    assert task_result.artifacts[0].content_hash
    assert task_result.retained_tabs
    assert task_result.retained_tabs[0].url.startswith("https://tmsearch.uspto.gov/")


@pytest.mark.asyncio
async def test_end_to_end():
    """Full planner->navigator->extractor->synthesizer pipeline against a live browser."""
    if not os.getenv("RUN_BROWSE_LIVE_TESTS"):
        pytest.skip("RUN_BROWSE_LIVE_TESTS is not enabled")

    result = await browse(
        "Go to https://tmsearch.uspto.gov/ and retrieve all cases related to "
        "Arash Samadani (as attorney)",
        planner_model="gpt-5.6-sol",
        navigator_model="gpt-5.6-sol",
        extractor_model="gpt-5.6-sol",
        synthesizer_model="gpt-5.6-sol",
        headless=False,
    )

    task_result = result.task_results[0]
    assert task_result.artifacts
    assert "158" in result.answer
