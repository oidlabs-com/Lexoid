"""Planner validation tests without a network model dependency."""

import pytest
from lexoid.core.browse.agents import validate_planned_task
from lexoid.core.browse.model_provider import LexoidChatClient, create_chat_client
from lexoid.core.browse.schemas import BrowseLimits

QUERY = "Go to https://tmsearch.uspto.gov/ and search records related to Arash Samadani"


def test_planner_accepts_user_supplied_url_and_host():
    task = validate_planned_task(
        QUERY,
        {
            "seed_urls": ["https://tmsearch.uspto.gov/"],
            "subject": "Arash Samadani",
            "requested_facts": ["matching records"],
            "allowed_domains": ["tmsearch.uspto.gov"],
        },
        BrowseLimits(),
    )
    assert task.subject == "Arash Samadani"


def test_planner_rejects_invented_url_and_domain():
    payload = {
        "seed_urls": ["https://evil.example/"],
        "subject": "Arash Samadani",
        "allowed_domains": ["evil.example"],
    }
    with pytest.raises(ValueError, match="invented a seed URL"):
        validate_planned_task(QUERY, payload, BrowseLimits())


def test_planner_preserves_user_filters():
    filter_query = (
        "Go to https://tmsearch.uspto.gov/ and retrieve all cases related to "
        "Arash Samadani as attorney"
    )
    task = validate_planned_task(
        filter_query,
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
    filter_query = (
        "Go to https://tmsearch.uspto.gov/ and retrieve all cases related to "
        "Arash Samadani as attorney"
    )
    payload = {
        "seed_urls": ["https://tmsearch.uspto.gov/"],
        "subject": "Arash Samadani",
        "allowed_domains": ["tmsearch.uspto.gov"],
        "constraints": {
            "filters": [{"field": "owner", "value": "Unrelated Person"}],
        },
    }

    with pytest.raises(ValueError, match="invented a filter value"):
        validate_planned_task(filter_query, payload, BrowseLimits())


@pytest.mark.asyncio
async def test_lexoid_client_uses_agent_framework_response_path(monkeypatch):
    from lexoid.core.browse import model_provider

    monkeypatch.setattr(model_provider, "get_api_provider_for_model", lambda _: "test")
    monkeypatch.setattr(
        model_provider,
        "create_response",
        lambda **_: {
            "response": '{"kind":"done"}',
            "usage": {"input": 2, "output": 3, "total": 5},
        },
    )

    response, usage = await LexoidChatClient("test-model").complete_json(
        "Return JSON.", "Complete."
    )

    assert response == '{"kind":"done"}'
    assert usage.total == 5


def test_openai_models_use_native_agent_framework_client(monkeypatch):
    from lexoid.core.browse import model_provider

    class NativeOpenAIClient:
        def __init__(self, *, model):
            self.model = model

    monkeypatch.setattr(model_provider, "OpenAIChatClient", NativeOpenAIClient)
    monkeypatch.setattr(
        model_provider, "get_api_provider_for_model", lambda _: "openai"
    )

    client = create_chat_client("gpt-5.6-sol")

    assert isinstance(client, NativeOpenAIClient)
    assert client.model == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_plan_task_emits_info_audit_log():
    from lexoid.core.browse.agents import plan_task
    from loguru import logger

    messages = []
    sink_id = logger.add(lambda msg: messages.append(msg), level="INFO")
    try:
        task, _ = await plan_task(
            "Go to https://tmsearch.uspto.gov/ and search for Arash Samadani",
            client=None,
            limits=BrowseLimits(),
        )
        assert task.seed_urls == ["https://tmsearch.uspto.gov/"]
        assert any("Initial Plan" in m and "tmsearch.uspto.gov" in m for m in messages)
    finally:
        logger.remove(sink_id)


@pytest.mark.asyncio
async def test_plan_task_truncates_long_subject_in_log():
    from lexoid.core.browse.agents import plan_task
    from loguru import logger

    long_query = "Go to https://tmsearch.uspto.gov/ " + ("longtext " * 35)
    messages = []
    sink_id = logger.add(lambda msg: messages.append(msg), level="INFO")
    try:
        task, _ = await plan_task(
            long_query,
            client=None,
            limits=BrowseLimits(),
        )
        plan_log = next(m for m in messages if "Initial Plan" in m)
        assert "..." in plan_log
    finally:
        logger.remove(sink_id)


def test_planner_strategy_validation_and_rendering():
    from lexoid.core.browse.agents import render_task_plan

    payload = {
        "seed_urls": ["https://tmsearch.uspto.gov/"],
        "subject": "Arash Samadani as attorney",
        "allowed_domains": ["tmsearch.uspto.gov"],
        "constraints": {
            "filters": [{"field": "attorney", "value": "Arash Samadani"}],
            "coverage": "all_matches",
        },
        "strategy": {
            "intent": "Find all trademark records where Arash Samadani is listed as attorney.",
            "approach": [
                "Open USPTO search interface",
                "Locate attorney search option",
                "Execute search and collect results",
            ],
            "navigation_guidance": [
                "Prefer attorney-specific field if available",
                "Do not confuse owner with attorney",
            ],
            "assumptions": [
                "Targeting attorney-of-record rather than examining attorney"
            ],
        },
    }
    task = validate_planned_task(
        "https://tmsearch.uspto.gov/ Arash Samadani as attorney",
        payload,
        BrowseLimits(),
    )
    assert task.strategy.intent.startswith("Find all trademark records")
    assert len(task.strategy.approach) == 3
    assert len(task.strategy.navigation_guidance) == 2
    assert len(task.strategy.assumptions) == 1

    rendered = render_task_plan(task)
    assert "Initial Plan task-1:" in rendered
    assert "Intent:" in rendered
    assert "Approach:" in rendered
    assert "1. Open USPTO search interface" in rendered
    assert "Navigation Guidance:" in rendered
    assert "Prefer attorney-specific field" in rendered
    assert "Assumptions:" in rendered
    assert "attorney-of-record" in rendered


@pytest.mark.asyncio
async def test_run_task_emits_plan_trace_event_and_records_outcome(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import BrowseTask, PlanStrategy

    monkeypatch.setattr(
        orchestrator,
        "ghost_get_html",
        lambda url, cfg: (
            "<html>content</html>",
            {"input": 0, "output": 0, "total": 0},
        ),
    )
    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
        strategy=PlanStrategy(
            intent="Search USPTO for Arash Samadani",
            approach=["Open page", "Verify records"],
            navigation_guidance=["Check results table"],
        ),
    )

    events = []
    result = await orchestrator.run_task(
        task,
        event_listener=events.append,
        html_fetcher=orchestrator.ghost_get_html,
    )

    assert events
    assert events[0].event == "plan"
    assert events[0].metadata["subject"] == "Arash Samadani"
    assert events[0].metadata["intent"] == "Search USPTO for Arash Samadani"
    assert events[0].metadata["approach"] == ["Open page", "Verify records"]
    assert events[0].metadata["navigation_guidance"] == ["Check results table"]

    # PlanOutcomeRecord is attached to task result
    task_res = result.task_results[0]
    assert task_res.plan_outcome is not None
    assert task_res.plan_outcome.task_id == task.task_id
    assert task_res.plan_outcome.intent == "Search USPTO for Arash Samadani"
    assert task_res.plan_outcome.stop_reason == "sufficient"
    assert task_res.plan_outcome.pages_captured == 1
