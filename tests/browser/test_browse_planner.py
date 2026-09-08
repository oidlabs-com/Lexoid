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
