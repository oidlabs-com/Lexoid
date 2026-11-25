"""Planner validation tests without a network model dependency."""

import json
from datetime import datetime, timezone

import pytest
from lexoid.core.browse import agents
from lexoid.core.browse.agents import validate_planned_task as _validate_planned_task
from lexoid.core.browse.model_provider import LexoidChatClient, create_chat_client
from lexoid.core.browse.policy import fallback_search_domains
from lexoid.core.browse.schemas import BrowseLimits

QUERY = "Go to https://tmsearch.uspto.gov/ and search records related to Arash Samadani"


def validate_planned_task(query, payload, limits):
    """Keep legacy planner fixtures explicit about their unrestricted scope."""
    return _validate_planned_task(
        query,
        {
            "source_scope": {"mode": "unrestricted", "evidence": None},
            **payload,
        },
        limits,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("invented_filter", [False, True])
async def test_planner_receives_current_date_and_preserves_search_assumptions(
    monkeypatch, invented_filter
):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls(2030, 6, 1, tzinfo=tz)

    query = "Plan a simple 2-day trip using https://www.google.com/travel/flights."
    assumptions = ["Use sample travel dates 2030-06-10 to 2030-06-11 for one adult."]

    async def fake_agent(client, name, instructions, prompt, **kwargs):
        assert name == "planner"
        assert prompt.endswith(
            f"current_date: 2030-06-01\ndefault_search_url: "
            f"{agents.DEFAULT_SEARCH_URL}\n\n{query}"
        )
        return json.dumps(
            {
                "seed_urls": ["https://www.google.com/travel/flights"],
                "subject": query,
                "source_scope": {"mode": "unrestricted", "evidence": None},
                "strategy": {"assumptions": assumptions},
                "constraints": {
                    "filters": [{"field": "departure date", "value": "2030-06-01"}]
                    if invented_filter
                    else []
                },
            }
        ), agents.BrowseUsage()

    monkeypatch.setattr(agents, "datetime", FrozenDatetime)
    monkeypatch.setattr(agents, "_run_json_agent", fake_agent)
    if invented_filter:
        with pytest.raises(ValueError, match="invented a filter value"):
            await agents.plan_task(query, object(), BrowseLimits())
        return
    task, _ = await agents.plan_task(query, object(), BrowseLimits())
    assert task.strategy.assumptions == assumptions
    assert task.constraints.filters == []
    assert task.requested_facts == []


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


@pytest.mark.parametrize(
    ("default_search_url", "expected_domain"),
    [
        ("https://www.google.com/", "google.com"),
        ("https://www.bing.com/", "bing.com"),
        ("https://search.brave.com/", "search.brave.com"),
    ],
)
def test_planner_defaults_open_ended_query_to_configured_search_provider(
    default_search_url, expected_domain
):
    task = _validate_planned_task(
        "Lisbon in March for two, foodies, no layovers",
        {
            "seed_urls": [],
            "inferred_seeds": [],
            "subject": "Find Lisbon travel options",
            "source_scope": {"mode": "unrestricted", "evidence": None},
        },
        BrowseLimits(),
        default_search_url=default_search_url,
    )

    assert task.seed_urls == [default_search_url]
    assert task.allowed_domains == [expected_domain]
    assert any(
        "configured default provider" in item for item in task.strategy.assumptions
    )
    assert any("No starting source was provided" in item for item in task.warnings)


def test_planner_does_not_default_a_restricted_source_scope():
    with pytest.raises(ValueError, match="restricted source scope"):
        _validate_planned_task(
            "Only search using Google for the SEC filing",
            {
                "seed_urls": [],
                "inferred_seeds": [],
                "subject": "Find SEC filing",
                "source_scope": {
                    "mode": "search_provider_only",
                    "evidence": "Only search using Google",
                },
            },
            BrowseLimits(),
        )


def test_planner_does_not_replace_an_omitted_user_source_with_default():
    with pytest.raises(ValueError, match="omitted a user-supplied source"):
        _validate_planned_task(
            "Search https://www.google.com/ for the SEC filing",
            {
                "seed_urls": [],
                "inferred_seeds": [],
                "subject": "Find SEC filing",
                "source_scope": {"mode": "unrestricted", "evidence": None},
            },
            BrowseLimits(),
        )


def test_planner_rejects_unsupported_default_search_provider():
    with pytest.raises(ValueError, match="supported search provider"):
        _validate_planned_task(
            "Lisbon in March for two",
            {
                "seed_urls": [],
                "inferred_seeds": [],
                "subject": "Find Lisbon travel options",
                "source_scope": {"mode": "unrestricted", "evidence": None},
            },
            BrowseLimits(),
            default_search_url="https://example.com/",
        )


@pytest.mark.parametrize(
    ("query", "seed", "scope", "evidence"),
    [
        (
            "Only search using Google at https://www.google.com/ to find the SEC filing and open the result.",
            "https://www.google.com/",
            "search_provider_only",
            "Only search using Google",
        ),
        (
            "Only use google.com (https://www.google.com/) to search for the SEC filing and open its result.",
            "https://google.com/",
            "search_provider_only",
            "Only use google.com",
        ),
        (
            "Google is my only search engine; use https://www.google.com/ to find the SEC filing and open it.",
            "https://www.google.com/",
            "search_provider_only",
            "Google is my only search engine",
        ),
        (
            "Only use sec.gov (https://sec.gov/) to find the filing.",
            "https://sec.gov/",
            "domain_only",
            "Only use sec.gov",
        ),
    ],
)
def test_planner_validates_and_preserves_restricted_source_scope(
    query, seed, scope, evidence
):
    domain = seed.split("//", 1)[1].split("/", 1)[0].removeprefix("www.")
    task = validate_planned_task(
        query,
        {
            "seed_urls": [seed],
            "subject": "Find filing",
            "allowed_domains": [domain],
            "source_scope": {"mode": scope, "evidence": evidence},
        },
        BrowseLimits(),
    )

    assert task.source_scope.mode == scope
    assert task.source_scope.evidence == evidence


def test_planner_keeps_starting_provider_unrestricted():
    query = "Start with Google (https://www.google.com/) and find the SEC filing."
    task = validate_planned_task(
        query,
        {
            "seed_urls": ["https://www.google.com/"],
            "subject": "Find filing",
            "allowed_domains": ["google.com"],
        },
        BrowseLimits(),
    )

    assert task.source_scope.mode == "unrestricted"


def test_planner_infers_restricted_search_provider_seed_without_url():
    query = "Google is my only search engine; find the SEC filing and open it."
    task = validate_planned_task(
        query,
        {
            "seed_urls": [],
            "inferred_seeds": [
                {
                    "url": "https://www.google.com/",
                    "source_text": "Google",
                    "rationale": "Named search provider",
                }
            ],
            "subject": "Find filing",
            "allowed_domains": ["google.com"],
            "source_scope": {
                "mode": "search_provider_only",
                "evidence": "Google is my only search engine",
            },
        },
        BrowseLimits(),
    )

    assert task.source_scope.mode == "search_provider_only"
    assert task.allowed_domains == ["google.com"]


def test_planner_allows_multiple_restricted_search_providers():
    query = "Use only Google and Bing to find the SEC filing."
    task = validate_planned_task(
        query,
        {
            "inferred_seeds": [
                {"url": "https://www.google.com/", "source_text": "Google"},
                {"url": "https://www.bing.com/", "source_text": "Bing"},
            ],
            "subject": "Find filing",
            "allowed_domains": ["google.com", "bing.com"],
            "source_scope": {
                "mode": "search_provider_only",
                "evidence": "Use only Google and Bing",
            },
        },
        BrowseLimits(),
    )

    assert task.source_scope.mode == "search_provider_only"
    assert sorted(task.allowed_domains) == ["bing.com", "google.com"]
    assert (
        fallback_search_domains(
            [seed.url for seed in task.inferred_seeds],
            task.allowed_domains,
            task.source_scope.mode,
        )
        == []
    )


def test_fallback_search_provider_order():
    assert fallback_search_domains(["https://www.google.com/"], ["google.com"]) == [
        "bing.com",
        "search.brave.com",
        "duckduckgo.com",
    ]


def test_planner_rejects_provider_restriction_without_provider_seed():
    query = "Only search using Google; use https://www.sec.gov/ for the filing."
    with pytest.raises(ValueError, match="requires a search provider seed"):
        validate_planned_task(
            query,
            {
                "seed_urls": ["https://www.sec.gov/"],
                "subject": "Find filing",
                "allowed_domains": ["sec.gov"],
                "source_scope": {
                    "mode": "search_provider_only",
                    "evidence": "Only search using Google",
                },
            },
            BrowseLimits(),
        )


def test_planner_rejects_evidence_for_unrestricted_scope():
    query = "Only use sec.gov (https://www.sec.gov/) for the filing."
    with pytest.raises(ValueError, match="cannot cite restriction text"):
        validate_planned_task(
            query,
            {
                "seed_urls": ["https://www.sec.gov/"],
                "subject": "Find filing",
                "allowed_domains": ["sec.gov"],
                "source_scope": {
                    "mode": "unrestricted",
                    "evidence": "Only use sec.gov",
                },
            },
            BrowseLimits(),
        )


def test_planner_allows_search_provider_and_site_in_domain_restriction():
    query = "Only use Google and sec.gov to find the filing."
    task = validate_planned_task(
        query,
        {
            "inferred_seeds": [
                {"url": "https://www.google.com/", "source_text": "Google"},
                {"url": "https://www.sec.gov/", "source_text": "sec.gov"},
            ],
            "subject": "Find filing",
            "allowed_domains": ["google.com", "sec.gov"],
            "source_scope": {
                "mode": "domain_only",
                "evidence": "Only use Google and sec.gov",
            },
        },
        BrowseLimits(),
    )

    assert task.source_scope.mode == "domain_only"
    assert sorted(task.allowed_domains) == ["google.com", "sec.gov"]


def test_planner_rejects_domains_outside_domain_only_restriction():
    query = "Only use sec.gov (https://sec.gov/) and Google (https://google.com/)."
    with pytest.raises(ValueError, match="outside the restriction"):
        validate_planned_task(
            query,
            {
                "seed_urls": ["https://sec.gov/", "https://google.com/"],
                "subject": "Find filing",
                "allowed_domains": ["sec.gov", "google.com"],
                "source_scope": {"mode": "domain_only", "evidence": "Only use sec.gov"},
            },
            BrowseLimits(),
        )


def test_planner_rejects_restriction_evidence_not_in_user_request():
    query = "Search using Google (https://www.google.com/) for the SEC filing."
    with pytest.raises(ValueError, match="source scope evidence"):
        validate_planned_task(
            query,
            {
                "seed_urls": ["https://www.google.com/"],
                "subject": "Find filing",
                "allowed_domains": ["google.com"],
                "source_scope": {
                    "mode": "search_provider_only",
                    "evidence": "Only search using Google",
                },
            },
            BrowseLimits(),
        )


def test_planner_rejects_missing_source_scope_policy():
    with pytest.raises(ValueError, match="omitted source scope policy"):
        _validate_planned_task(
            QUERY,
            {
                "seed_urls": ["https://tmsearch.uspto.gov/"],
                "subject": "Find records",
                "allowed_domains": ["tmsearch.uspto.gov"],
            },
            BrowseLimits(),
        )


@pytest.mark.parametrize(
    ("query", "expected_scope"),
    [
        ("Use https://www.google.com/ to find the SEC filing.", "search_provider_only"),
        ("Use https://www.sec.gov/ to find the filing.", "domain_only"),
        (
            "Use https://www.google.com/ and https://www.bing.com/ to find it.",
            "search_provider_only",
        ),
        (
            "Use https://www.google.com/ and https://www.sec.gov/ to find it.",
            "domain_only",
        ),
    ],
)
def test_no_planner_defaults_to_conservative_source_scope(query, expected_scope):
    task = agents.task_from_query(query, BrowseLimits())

    assert task.source_scope.mode == expected_scope
    assert task.source_scope.evidence is None
    assert "No planning model is available" in task.strategy.assumptions[0]


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


def test_planner_separates_evaluation_criteria_from_hard_filters():
    query = (
        "Use https://www.loopnet.com/ to shortlist properties likely suited for "
        "opening a Korean BBQ restaurant. Minimum Size >= 5,000 SF"
    )
    task = validate_planned_task(
        query,
        {
            "seed_urls": ["https://www.loopnet.com/"],
            "subject": "Korean BBQ restaurant properties",
            "allowed_domains": ["loopnet.com"],
            "constraints": {
                "filters": [
                    {
                        "field": "Minimum Size",
                        "operator": "unspecified",
                        "value": "5,000 SF",
                    }
                ],
                "evaluation_criteria": [
                    "likely suited for opening a Korean BBQ restaurant"
                ],
            },
        },
        BrowseLimits(),
    )

    assert len(task.constraints.filters) == 1
    assert task.constraints.filters[0].value == "5,000 SF"
    assert task.constraints.evaluation_criteria == [
        "likely suited for opening a Korean BBQ restaurant"
    ]


def test_planner_drops_invented_evaluation_criteria_with_warning():
    query = "Use https://www.loopnet.com/ and find commercial listings."
    payload = {
        "seed_urls": ["https://www.loopnet.com/"],
        "subject": "commercial listings",
        "allowed_domains": ["loopnet.com"],
        "constraints": {
            "evaluation_criteria": ["near a subway station"],
        },
    }

    task = validate_planned_task(query, payload, BrowseLimits())

    assert task.constraints.evaluation_criteria == []
    assert any("Dropped evaluation criterion" in warning for warning in task.warnings)


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
    assert "Evaluation Criteria:" not in rendered
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
    assert events[0].metadata["source_scope"] == {
        "mode": "unrestricted",
        "evidence": None,
    }

    # PlanOutcomeRecord is attached to task result
    task_res = result.task_results[0]
    assert task_res.plan_outcome is not None
    assert task_res.plan_outcome.task_id == task.task_id
    assert task_res.plan_outcome.intent == "Search USPTO for Arash Samadani"
    assert task_res.plan_outcome.stop_reason == "sufficient"
    assert task_res.plan_outcome.pages_captured == 1


def test_extract_query_sources_parentheses_and_punctuation():
    from lexoid.core.browse.policy import extract_query_sources

    query = (
        "First, on Google (https://www.google.com/), search for Baltimore weather. "
        "Then go to Wunderground (https://www.wunderground.com/) and Syracuse."
    )
    sources = extract_query_sources(query)
    assert "https://www.google.com/" in sources
    assert "https://www.wunderground.com/" in sources


def test_extract_query_sources_literal_domains():
    from lexoid.core.browse.policy import extract_query_sources

    query = (
        "Check weather.gov and forecast.weather.gov for alerts. "
        "Do not email support@example.com, e.g. for questions."
    )
    sources = extract_query_sources(query)
    assert "https://weather.gov/" in sources
    assert "https://forecast.weather.gov/" in sources
    assert not any("example.com" in s for s in sources)


def test_validate_seed_url_security_checks():
    from lexoid.core.browse.policy import validate_seed_url

    with pytest.raises(ValueError, match="must use https"):
        validate_seed_url("http://insecure.example.com/")

    with pytest.raises(ValueError, match="embedded credentials"):
        validate_seed_url("https://user:pass@example.com/")

    with pytest.raises(ValueError, match="unsupported port"):
        validate_seed_url("https://example.com:8080/")

    with pytest.raises(ValueError, match="IP address or localhost"):
        validate_seed_url("https://127.0.0.1/")

    with pytest.raises(ValueError, match="IP address or localhost"):
        validate_seed_url("https://localhost/")

    with pytest.raises(ValueError, match="at least two labels"):
        validate_seed_url("https://gov/")

    with pytest.raises(ValueError, match="public suffix or shared hosting"):
        validate_seed_url("https://co.uk/")

    with pytest.raises(ValueError, match="public suffix or shared hosting"):
        validate_seed_url("https://github.io/")


def test_derive_allowed_domains_strips_www_and_subdomain_scope():
    from lexoid.core.browse.policy import derive_allowed_domains, is_allowed_url

    allowed = derive_allowed_domains(["https://www.wunderground.com/"])
    assert allowed == ["wunderground.com"]
    assert is_allowed_url("https://wunderground.com/page", allowed)
    assert is_allowed_url("https://www.wunderground.com/page", allowed)
    assert is_allowed_url("https://sub.wunderground.com/page", allowed)
    assert not is_allowed_url("https://other.com/page", allowed)
    assert not is_allowed_url("https://wunderground.com.evil.com/page", allowed)


def test_planner_with_inferred_seeds():
    weather_query = (
        "First, on Google (https://www.google.com/), search for Baltimore weather. "
        "Then go to Wunderground (https://www.wunderground.com/) and Syracuse. "
        "After that, use the National Weather Service forecast page for Rittman."
    )
    payload = {
        "seed_urls": ["https://www.google.com/", "https://www.wunderground.com/"],
        "inferred_seeds": [
            {
                "url": "https://weather.gov/",
                "source_text": "National Weather Service",
                "rationale": "Official domain for NWS",
            }
        ],
        "subject": "weather risk snapshot",
        "allowed_domains": ["google.com", "wunderground.com", "weather.gov"],
    }
    task = validate_planned_task(weather_query, payload, BrowseLimits())
    assert len(task.seed_urls) == 2
    assert len(task.inferred_seeds) == 1
    assert task.inferred_seeds[0].url == "https://weather.gov/"
    assert task.inferred_seeds[0].source_text == "National Weather Service"
    assert "google.com" in task.allowed_domains
    assert "wunderground.com" in task.allowed_domains
    assert "weather.gov" in task.allowed_domains


def test_planner_rejects_inferred_seed_not_in_query():
    weather_query = (
        "First, on Google (https://www.google.com/), search for Baltimore weather."
    )
    payload = {
        "seed_urls": ["https://www.google.com/"],
        "inferred_seeds": [
            {
                "url": "https://accuweather.com/",
                "source_text": "AccuWeather",
                "rationale": "Commercial weather",
            }
        ],
        "subject": "weather",
        "allowed_domains": ["google.com", "accuweather.com"],
    }
    with pytest.raises(ValueError, match="without source text in query"):
        validate_planned_task(weather_query, payload, BrowseLimits())


def test_planner_accepts_inferred_seed_with_non_source_restriction():
    query = "Check National Weather Service records. Only use data from 2024."
    payload = {
        "inferred_seeds": [
            {
                "url": "https://weather.gov/",
                "source_text": "National Weather Service",
                "rationale": "Official domain for NWS",
            }
        ],
        "subject": "weather",
        "allowed_domains": ["weather.gov"],
    }
    task = validate_planned_task(query, payload, BrowseLimits())
    assert [seed.url for seed in task.inferred_seeds] == ["https://weather.gov/"]
    assert task.allowed_domains == ["weather.gov"]


def test_render_task_plan_shows_inferred_seeds():
    from lexoid.core.browse.agents import render_task_plan

    task = validate_planned_task(
        "Check National Weather Service for rain",
        {
            "seed_urls": [],
            "inferred_seeds": [
                {
                    "url": "https://weather.gov/",
                    "source_text": "National Weather Service",
                    "rationale": "NWS",
                }
            ],
            "subject": "rain",
            "allowed_domains": ["weather.gov"],
        },
        BrowseLimits(),
    )
    rendered = render_task_plan(task)
    assert "Inferred Seeds:" in rendered
    assert "inferred, not verified" in rendered
