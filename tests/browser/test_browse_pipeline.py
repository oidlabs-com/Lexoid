"""Tests for the initial typed single-task browse executor."""

import os

import pytest
from lexoid.api import BrowseModelConfig, browse
from lexoid.core.browse.evidence import validated_claims
from lexoid.core.browse.schemas import (
    BrowseTask,
    BrowseTerminalState,
    EvidenceClaim,
    PageArtifact,
)
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_browse_requires_explicit_https_url():
    with pytest.raises(ValueError, match="clarification_needed"):
        await browse("search trademark records")


@pytest.mark.asyncio
async def test_browse_rejects_unsupported_model_before_capture():
    with pytest.raises(ValueError, match="model_unsupported"):
        await browse("https://tmsearch.uspto.gov/", model_config="unknown-model")

    with pytest.raises(ValueError, match="model_unsupported"):
        await browse(
            "https://tmsearch.uspto.gov/",
            model_config={"navigator": "unknown-model"},
        )


def test_browse_model_config_resolution():
    # String shorthand sets default for all roles
    cfg_str = BrowseModelConfig.from_value("gpt-5.6-sol")
    assert cfg_str.for_role("planner") == "gpt-5.6-sol"
    assert cfg_str.for_role("navigator") == "gpt-5.6-sol"
    assert cfg_str.for_role("extractor") == "gpt-5.6-sol"
    assert cfg_str.for_role("synthesizer") == "gpt-5.6-sol"

    # Dict with default baseline + role override
    cfg_dict = BrowseModelConfig.from_value(
        {"default": "gpt-4o", "navigator": "gpt-5.6-sol"}
    )
    assert cfg_dict.for_role("planner") == "gpt-4o"
    assert cfg_dict.for_role("navigator") == "gpt-5.6-sol"
    assert cfg_dict.for_role("extractor") == "gpt-4o"
    assert cfg_dict.for_role("synthesizer") == "gpt-4o"

    # Selective role with no default
    cfg_selective = BrowseModelConfig.from_value({"navigator": "gpt-5.6-sol"})
    assert cfg_selective.for_role("planner") is None
    assert cfg_selective.for_role("navigator") == "gpt-5.6-sol"
    assert cfg_selective.for_role("extractor") is None
    assert cfg_selective.for_role("synthesizer") is None

    # None value produces empty config
    cfg_none = BrowseModelConfig.from_value(None)
    assert cfg_none.for_role("planner") is None
    assert cfg_none.for_role("navigator") is None

    # Unknown role lookup raises ValueError
    with pytest.raises(ValueError, match="Unknown browse role"):
        cfg_str.for_role("invalid_role")


def test_browse_model_config_reasoning_effort():
    # Case 1: default with explicit dict containing model and reasoning
    cfg1 = BrowseModelConfig.from_value(
        {"default": {"model": "gpt-5.6-mini", "reasoning": {"effort": "low"}}}
    )
    assert cfg1.for_role("planner") == "gpt-5.6-mini"
    assert cfg1.reasoning_effort_for_role("planner") == "low"
    assert cfg1.for_role("navigator") == "gpt-5.6-mini"
    assert cfg1.reasoning_effort_for_role("navigator") == "low"
    assert cfg1.for_role("extractor") == "gpt-5.6-mini"
    assert cfg1.reasoning_effort_for_role("extractor") == "low"
    assert cfg1.for_role("synthesizer") == "gpt-5.6-mini"
    assert cfg1.reasoning_effort_for_role("synthesizer") == "low"

    # Case 2: default as string with reasoning model ("medium" by default)
    cfg2 = BrowseModelConfig.from_value({"default": "gpt-5.6-sol"})
    assert cfg2.for_role("planner") == "gpt-5.6-sol"
    assert cfg2.reasoning_effort_for_role("planner") == "medium"
    assert cfg2.for_role("navigator") == "gpt-5.6-sol"
    assert cfg2.reasoning_effort_for_role("navigator") == "medium"

    # String shorthand also defaults reasoning models to "medium"
    cfg2_str = BrowseModelConfig.from_value("gpt-5.6-sol")
    assert cfg2_str.for_role("planner") == "gpt-5.6-sol"
    assert cfg2_str.reasoning_effort_for_role("planner") == "medium"

    # Case 3: default is non-reasoning, navigator role override has reasoning dict
    cfg3 = BrowseModelConfig.from_value(
        {
            "default": "gpt-4o",
            "navigator": {"model": "gpt-5.6-sol", "reasoning": {"effort": "low"}},
        }
    )
    assert cfg3.for_role("planner") == "gpt-4o"
    assert cfg3.reasoning_effort_for_role("planner") is None
    assert cfg3.for_role("navigator") == "gpt-5.6-sol"
    assert cfg3.reasoning_effort_for_role("navigator") == "low"
    assert cfg3.for_role("extractor") == "gpt-4o"
    assert cfg3.reasoning_effort_for_role("extractor") is None

    # Case 4: explicit reasoning dictionary and options
    cfg4 = BrowseModelConfig.from_value(
        {
            "planner": {
                "model": "gpt-5.6-sol",
                "reasoning": {"effort": "high", "summary": "detailed"},
                "options": {"verbosity": "high"},
            },
            "navigator": {
                "model": "gpt-5.6-sol",
                "reasoning": {"effort": "low"},
            },
        }
    )
    assert cfg4.for_role("planner") == "gpt-5.6-sol"
    assert cfg4.options_for_role("planner") == {
        "reasoning": {"effort": "high", "summary": "detailed"},
        "verbosity": "high",
    }
    assert cfg4.reasoning_effort_for_role("planner") == "high"
    assert cfg4.options_for_role("navigator") == {"reasoning": {"effort": "low"}}
    assert cfg4.reasoning_effort_for_role("navigator") == "low"


def test_browse_model_config_validation():
    # Misspelled role name is rejected immediately
    with pytest.raises(ValidationError):
        BrowseModelConfig.from_value({"navigtor": "gpt-5.6-sol"})

    # Invalid reasoning format (must be dict) is rejected
    with pytest.raises(ValidationError):
        BrowseModelConfig.from_value(
            {"default": {"model": "gpt-5.6-mini", "reasoning": "invalid"}}
        )

    # Extra keys inside role config are rejected
    with pytest.raises(ValidationError):
        BrowseModelConfig.from_value(
            {"default": {"model": "gpt-5.6-mini", "unknown_key": "val"}}
        )

    # Invalid type is rejected
    with pytest.raises(TypeError, match="model_config must be str, dict"):
        BrowseModelConfig.from_value(123)  # type: ignore[arg-type]


def test_create_chat_client_creates_client(monkeypatch):
    from lexoid.core.browse.model_provider import create_chat_client

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = create_chat_client("gpt-5.6-sol")
    assert client is not None


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


def test_verify_constraints_checks_value_presence():
    from lexoid.core.browse.evidence import verify_constraints
    from lexoid.core.browse.schemas import TaskFilter

    claim = EvidenceClaim(
        claim_id="claim-1",
        text="The country is Mexico.",
        quote="Respondent is a citizen of Mexico.",
        artifact_id="artifact-1",
        source_url="https://example.test/",
    )
    filters = [
        TaskFilter(field="country_of_origin", operator="equals", value="Mexico"),
        TaskFilter(field="country_of_origin", operator="equals", value="Canada"),
    ]

    checks = verify_constraints(filters, [claim])
    assert checks[0].field == "country_of_origin"
    assert checks[0].value == "Mexico"
    assert checks[0].value_present is True
    assert checks[0].supporting_claim_ids == ["claim-1"]

    assert checks[1].field == "country_of_origin"
    assert checks[1].value == "Canada"
    assert checks[1].value_present is False
    assert checks[1].supporting_claim_ids == []


def test_public_schemas_produce_json_schema():
    schema = BrowseTask.model_json_schema()

    assert schema["properties"]["seed_urls"]["type"] == "array"
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_synthesizer_payload_includes_intent_and_formats_answer(monkeypatch):
    import json

    from lexoid.core.browse import agents
    from lexoid.core.browse.schemas import BrowseUsage, CoverageReport, PlanStrategy

    captured_prompt = []

    async def fake_run_json_agent(client, name, instructions, prompt, **kwargs):
        captured_prompt.append((instructions, json.loads(prompt)))
        answer_json = json.dumps(
            {
                "answer": "Found 1 matching case for Arash Samadani as attorney.",
                "claim_ids": ["claim-1"],
            }
        )
        return answer_json, BrowseUsage(input=10, output=10, total=20)

    monkeypatch.setattr(agents, "_run_json_agent", fake_run_json_agent)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani as attorney",
        allowed_domains=["tmsearch.uspto.gov"],
        strategy=PlanStrategy(
            intent="Find all trademark cases where Arash Samadani is listed as attorney."
        ),
    )
    claims = [
        EvidenceClaim(
            claim_id="claim-1",
            text="Arash Samadani listed as attorney",
            quote="Arash Samadani",
            artifact_id="art-1",
            source_url="https://tmsearch.uspto.gov/",
        )
    ]
    coverage = CoverageReport(
        pages_captured=1,
        stop_reason="sufficient",
        answerability="sufficient",
        validated_claims=1,
    )

    answer, cited_ids, usage = await agents.synthesize_answer(
        client=object(),
        claims=claims,
        capture_complete=True,
        task=task,
        coverage=coverage,
    )

    assert "Direct answer first" in captured_prompt[0][0]
    payload = captured_prompt[0][1]
    assert (
        payload["task"]["intent"]
        == "Find all trademark cases where Arash Samadani is listed as attorney."
    )
    assert answer == "Found 1 matching case for Arash Samadani as attorney."
    assert cited_ids == ["claim-1"]
    assert usage.total == 20


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
@pytest.mark.parametrize(
    "query, expected_text",
    [
        # (
        #     """Go to https://tmsearch.uspto.gov/ and retrieve all cases related to Arash Samadani (as attorney)""",
        #     "158",
        # ),
        # (
        #     """Go to https://tmsearch.uspto.gov/ and retrieve all cases for Arash Samadani as attorney, filter only live cases.""",
        #     "44",
        # ),
        (
            """Got to EOIR, https://acis.eoir.justice.gov, and get the updated case
            information for alien number: 123-456-789, country of origin - Mexico""",
            "No case found",
        ),
        # (
        #     """Use https://www.loopnet.com/search/commercial-real-estate/irvine-ca/for-lease/ and shortlist 3 properties likely suited for opening a Korean BBQ restaurant.
        #     Additional criteria:
        #     - 'Minimum Size'>='5,000 SF'
        #     Give me street addresses (sorted by price low to high).
        #     """,
        #     "2626–2646 Dupont Dr, Irvine, CA 92612",
        # ),
    ],
)
async def test_end_to_end(query, expected_text):
    """Full planner->navigator->extractor->synthesizer pipeline against a live browser."""
    if not os.getenv("RUN_BROWSE_LIVE_TESTS"):
        pytest.skip("RUN_BROWSE_LIVE_TESTS is not enabled")

    result = await browse(
        query,
        model_config="gpt-5.6-sol",
        headless=False,
    )

    task_result = result.task_results[0]
    assert task_result.artifacts
    norm_expected = expected_text.replace("–", "-")
    assert (
        expected_text in result.answer
        or norm_expected in result.answer.replace("–", "-")
        or any(
            expected_text in artifact.text
            or norm_expected in artifact.text.replace("–", "-")
            for artifact in task_result.artifacts
        )
    )
