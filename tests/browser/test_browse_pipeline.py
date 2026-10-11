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
    assert cfg_str.for_role("assessor") == "gpt-5.6-sol"
    assert cfg_str.for_role("extractor") == "gpt-5.6-sol"
    assert cfg_str.for_role("synthesizer") == "gpt-5.6-sol"

    # Dict with default baseline + role override
    cfg_dict = BrowseModelConfig.from_value(
        {"default": "gpt-6-luna", "navigator": "gpt-5.6-sol"}
    )
    assert cfg_dict.for_role("planner") == "gpt-6-luna"
    assert cfg_dict.for_role("navigator") == "gpt-5.6-sol"
    assert cfg_dict.for_role("assessor") == "gpt-6-luna"
    assert cfg_dict.for_role("extractor") == "gpt-6-luna"
    assert cfg_dict.for_role("synthesizer") == "gpt-6-luna"

    # Selective role with no default
    cfg_selective = BrowseModelConfig.from_value({"navigator": "gpt-5.6-sol"})
    assert cfg_selective.for_role("planner") is None
    assert cfg_selective.for_role("navigator") == "gpt-5.6-sol"
    assert cfg_selective.for_role("assessor") is None
    assert cfg_selective.for_role("extractor") is None
    assert cfg_selective.for_role("synthesizer") is None

    # Assessor falls back to extractor when no assessor override is provided
    cfg_extractor_fallback = BrowseModelConfig.from_value(
        {"default": "gpt-5.6-sol", "extractor": "gpt-6-luna"}
    )
    assert cfg_extractor_fallback.for_role("extractor") == "gpt-6-luna"
    assert cfg_extractor_fallback.for_role("assessor") == "gpt-6-luna"

    # Assessor explicit override takes precedence over extractor
    cfg_assessor_override = BrowseModelConfig.from_value(
        {"extractor": "gpt-6-luna", "assessor": "gpt-5.6-sol"}
    )
    assert cfg_assessor_override.for_role("extractor") == "gpt-6-luna"
    assert cfg_assessor_override.for_role("assessor") == "gpt-5.6-sol"

    # None value produces empty config
    cfg_none = BrowseModelConfig.from_value(None)
    assert cfg_none.for_role("planner") is None
    assert cfg_none.for_role("navigator") is None
    assert cfg_none.for_role("assessor") is None

    # Unknown role lookup raises ValueError
    with pytest.raises(ValueError, match="Unknown browse role"):
        cfg_str.for_role("invalid_role")


def test_browse_model_config_reasoning_effort():
    # Case 1: default with explicit dict containing model and reasoning
    cfg1 = BrowseModelConfig.from_value(
        {"default": {"model": "gpt-6-luna", "reasoning": {"effort": "low"}}}
    )
    assert cfg1.for_role("planner") == "gpt-6-luna"
    assert cfg1.reasoning_effort_for_role("planner") == "low"
    assert cfg1.for_role("navigator") == "gpt-6-luna"
    assert cfg1.reasoning_effort_for_role("navigator") == "low"
    assert cfg1.for_role("extractor") == "gpt-6-luna"
    assert cfg1.reasoning_effort_for_role("extractor") == "low"
    assert cfg1.for_role("assessor") == "gpt-6-luna"
    assert cfg1.reasoning_effort_for_role("assessor") == "low"
    assert cfg1.for_role("synthesizer") == "gpt-6-luna"
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
            "default": "gpt-6-luna",
            "navigator": {"model": "gpt-5.6-sol", "reasoning": {"effort": "low"}},
        }
    )
    assert cfg3.for_role("planner") == "gpt-6-luna"
    assert cfg3.reasoning_effort_for_role("planner") is None
    assert cfg3.for_role("navigator") == "gpt-5.6-sol"
    assert cfg3.reasoning_effort_for_role("navigator") == "low"
    assert cfg3.for_role("extractor") == "gpt-6-luna"
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

    # Case 5: assessor inherits extractor reasoning effort when not explicitly set
    cfg5 = BrowseModelConfig.from_value(
        {
            "default": "gpt-6-luna",
            "extractor": {"model": "gpt-5.6-sol", "reasoning": {"effort": "low"}},
        }
    )
    assert cfg5.for_role("assessor") == "gpt-5.6-sol"
    assert cfg5.reasoning_effort_for_role("assessor") == "low"

    # Case 6: assessor explicit reasoning overrides extractor
    cfg6 = BrowseModelConfig.from_value(
        {
            "extractor": {"model": "gpt-5.6-sol", "reasoning": {"effort": "low"}},
            "assessor": {"model": "gpt-5.6-sol", "reasoning": {"effort": "high"}},
        }
    )
    assert cfg6.for_role("assessor") == "gpt-5.6-sol"
    assert cfg6.reasoning_effort_for_role("assessor") == "high"


def test_browse_model_config_validation():
    # Misspelled role name is rejected immediately
    with pytest.raises(ValidationError):
        BrowseModelConfig.from_value({"navigtor": "gpt-5.6-sol"})

    # Invalid reasoning format (must be dict) is rejected
    with pytest.raises(ValidationError):
        BrowseModelConfig.from_value(
            {"default": {"model": "gpt-6-luna", "reasoning": "invalid"}}
        )

    # Extra keys inside role config are rejected
    with pytest.raises(ValidationError):
        BrowseModelConfig.from_value(
            {"default": {"model": "gpt-6-luna", "unknown_key": "val"}}
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
    from lexoid.core.browse.schemas import (
        BrowseUsage,
        CandidateAssessment,
        CandidateCriterionEvidence,
        CoverageReport,
        PlanStrategy,
        SynthesisAssessment,
        TaskConstraints,
    )

    captured_prompt = []

    async def fake_run_json_agent(client, name, instructions, prompt, **kwargs):
        captured_prompt.append((instructions, json.loads(prompt)))
        answer_json = json.dumps(
            {
                "answer": "Found 1 matching case for Arash Samadani as attorney.",
                "claim_ids": ["claim-1"],
                "assessments": [
                    {
                        "statement": "Likely relevant based on the attorney match.",
                        "based_on_claim_ids": ["claim-1"],
                    }
                ],
            }
        )
        return answer_json, BrowseUsage(input=10, output=10, total=20)

    monkeypatch.setattr(agents, "_run_json_agent", fake_run_json_agent)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani as attorney",
        allowed_domains=["tmsearch.uspto.gov"],
        constraints=TaskConstraints(
            evaluation_criteria=["likely relevant to the request"]
        ),
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

    candidate_assessments = [
        CandidateAssessment(
            label="Record 1",
            source_url="https://tmsearch.uspto.gov/",
            criteria_support=[
                CandidateCriterionEvidence(
                    criterion="likely relevant to the request",
                    assessment="supported",
                    claim_ids=["claim-1"],
                )
            ],
        )
    ]
    answer, cited_ids, assessments, usage = await agents.synthesize_answer(
        client=object(),
        claims=claims,
        capture_complete=True,
        task=task,
        coverage=coverage,
        candidate_assessments=candidate_assessments,
    )

    assert "Direct answer first" in captured_prompt[0][0]
    payload = captured_prompt[0][1]
    assert "must not repeat non-verbatim judgments" in captured_prompt[0][0]
    assert (
        payload["task"]["intent"]
        == "Find all trademark cases where Arash Samadani is listed as attorney."
    )
    assert payload["task"]["constraints"]["evaluation_criteria"] == [
        "likely relevant to the request"
    ]
    assert payload["candidate_assessments"][0]["label"] == "Record 1"
    assert answer == "Found 1 matching case for Arash Samadani as attorney."
    assert cited_ids == ["claim-1"]
    assert assessments == [
        SynthesisAssessment(
            statement="Likely relevant based on the attorney match.",
            based_on_claim_ids=["claim-1"],
        )
    ]
    assert usage.total == 20


@pytest.mark.asyncio
async def test_assessor_receives_existing_claim_and_attempt_context(monkeypatch):
    import json

    from lexoid.core.browse import agents
    from lexoid.core.browse.schemas import BrowseUsage, PageArtifact

    captured = []

    async def fake_run_json_agent(client, name, instructions, prompt, **kwargs):
        captured.append((instructions, json.loads(prompt)))
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "A former restaurant use is listed.",
                        "quote": "Former restaurant use",
                        "artifact_id": "artifact-2",
                        "source_url": "https://example.test/listing/2",
                    }
                ],
                "candidates": [
                    {
                        "label": "Listing B",
                        "source_url": "https://example.test/listing/2",
                        "criteria_support": [
                            {
                                "criterion": "Korean BBQ suitability",
                                "assessment": "supported",
                                "claim_ids": ["claim-4"],
                            }
                        ],
                    }
                ],
                "answerability": "partial",
                "gaps": ["Listing B: ventilation capacity is not stated"],
                "next_action": "investigate",
                "next_action_reason": "Check another relevant listing fact.",
                "objective": "Inspect Listing B for kitchen ventilation details.",
            }
        ), BrowseUsage()

    monkeypatch.setattr(agents, "_run_json_agent", fake_run_json_agent)
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="Korean BBQ properties",
        allowed_domains=["example.test"],
    )
    prior = EvidenceClaim(
        claim_id="claim-3",
        text="Listing A is 5,200 SF.",
        quote="5,200 SF",
        artifact_id="artifact-1",
        source_url="https://example.test/listing/1",
    )
    artifact = PageArtifact(
        artifact_id="artifact-2",
        url="https://example.test/listing/2",
        tab_id="tab-1",
        content_hash="hash-2",
        text="Former restaurant use",
    )
    older_claim = prior.model_copy(
        update={"claim_id": "claim-1", "text": "Older verified listing fact."}
    )

    assessment, claims, _ = await agents.assess_page(
        object(),
        task,
        artifact,
        [older_claim, prior],
        [],
        prior_context={
            "captured_urls": [prior.source_url, artifact.url],
            "attempted_objectives": ["Inspect Listing A -> results_ready"],
        },
    )

    payload = captured[0][1]
    assert "Return every" in captured[0][0]
    assert payload["prior_claims"][0]["source_url"] == prior.source_url
    assert payload["captured_urls"] == [prior.source_url, artifact.url]
    assert payload["attempted_objectives"] == ["Inspect Listing A -> results_ready"]
    assert payload["next_claim_id"] == "claim-4"
    assert claims[0].claim_id == "claim-4"
    assert assessment.candidates[0].criteria_support[0].claim_ids == ["claim-4"]


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
        # (
        #     """Got to EOIR, https://acis.eoir.justice.gov, and get the updated case
        #     information for alien number: 123-456-789, country of origin - Mexico""",
        #     "No case found",
        # ),
        # (
        #     """Use https://www.loopnet.com/search/commercial-real-estate/irvine-ca/for-lease/ and shortlist 3 properties likely suited for opening a Korean BBQ restaurant.
        #     Additional criteria:
        #     - 'Minimum Size'>='5,000 SF'
        #     Give me street addresses (sorted by price low to high).
        #     """,
        #     "2626–2646 Dupont Dr, Irvine",
        # ),
        (
            """I’m trying to decide whether driving this week is a bad idea,
                so can you build me a quick weather risk snapshot that starts with what it feels like right now and then widens out to the bigger trouble spots?
                First, on Google (https://www.google.com/), search for Baltimore, Maryland weather and grab the current temperature plus the plain-English condition like cloudy, sunny, rain, or whatever it says,
                just so I have a baseline for home conditions.
                Then go to Wunderground (https://www.wunderground.com/) and look up Syracuse, New York, and check the 10-day/7-day style forecast to find the lowest temperature expected over the next 7 days, including which day it happens, because I want to compare that colder destination against Baltimore.
                After that, use the National Weather Service forecast page for the Rittman, Ohio area near Marshallville and tell me what the current forecast says and whether there are any active alerts posted there, since that would really affect an Ohio leg of the drive; please open the actual forecast page and leave it visible so I can see the alert area and forecast text myself.
                Finally, go to the NWS Mount Holly page, find the winter forecast graphic, and report the snowfall amount shown there so I can tell whether the Mid-Atlantic part looks like a nuisance event or something more serious; if the graphic opens separately, leave that tab open too so I can look at the map.
                In the end, send me a short location-by-location summary with the key weather risk for Baltimore, Syracuse, Rittman/Marshallville, and the Mount Holly region.
            """,
            "Rittman",
        )
    ],
)
async def test_end_to_end(query, expected_text):
    """Full planner->navigator->extractor->synthesizer pipeline against a live browser."""
    if not os.getenv("RUN_BROWSE_LIVE_TESTS"):
        pytest.skip("RUN_BROWSE_LIVE_TESTS is not enabled")

    _mc = {
        "planner": {
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "medium", "summary": "detailed"},
            "options": {"verbosity": "high"},
        },
        "navigator": {
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "medium"},
            "options": {"verbosity": "high"},
        },
        "assessor": {"model": "gpt-6-luna", "reasoning": {"effort": "high"}},
        "extractor": {"model": "gpt-6-luna", "reasoning": {"effort": "high"}},
        "synthesizer": {"model": "gpt-6-luna", "reasoning": {"effort": "medium"}},
    }
    # or
    # _mc = "gpt-5.6-sol"
    result = await browse(
        query,
        model_config=_mc,
        headless=False,
    )

    task_result = result.task_results[0]
    assert task_result.artifacts
    norm_expected = expected_text.replace("–", "-")
    print("Response:\n", result.answer)
    assert (
        expected_text in result.answer
        or norm_expected in result.answer.replace("–", "-")
        or any(
            expected_text in artifact.text
            or norm_expected in artifact.text.replace("–", "-")
            for artifact in task_result.artifacts
        )
    )
