"""Deterministic safety tests for Slice 1 browse policy."""

import pytest
from lexoid.core.browse.policy import (
    PolicyDecision,
    authorize,
    fallback_search_domains,
    is_allowed_url,
    search_discovery_domain,
)
from lexoid.core.browse.schemas import BrowseErrorCode, BrowserAction


@pytest.mark.parametrize(
    ("seed", "initial_domains", "enabled"),
    [
        ("https://www.google.com/", ["google.com"], True),
        ("https://bing.com/", ["bing.com"], True),
        ("https://search.brave.com/", ["brave.com"], True),
        ("https://example.com/", ["example.com"], False),
        ("https://example.com/", ["example.com", "google.com"], False),
        ("https://maps.google.com/", ["google.com"], False),
        ("https://google.com.evil.example/", ["evil.example"], False),
        ("https://google.com/", ["example.com"], False),
        ("http://google.com/", ["google.com"], False),
    ],
)
def test_fallback_search_domains_require_initial_search_seed(
    seed, initial_domains, enabled
):
    fallbacks = fallback_search_domains([seed], initial_domains)
    assert bool(fallbacks) is enabled
    if enabled:
        assert is_allowed_url("https://www.bing.com/", initial_domains + fallbacks)
        assert not is_allowed_url("https://unrelated.com/", initial_domains + fallbacks)
        assert not is_allowed_url("https://bing.com.evil.example/", initial_domains + fallbacks)
        assert not is_allowed_url("http://bing.com/", initial_domains + fallbacks)
        assert len(fallbacks) == len(set(fallbacks))
        assert not set(fallbacks).intersection(initial_domains)


def test_navigation_requires_allowlisted_domain():
    allowed = ["tmsearch.uspto.gov"]
    assert (
        authorize(
            BrowserAction(kind="navigate", url="https://tmsearch.uspto.gov/search"),
            allowed,
        ).decision
        is PolicyDecision.ALLOW
    )

    result = authorize(
        BrowserAction(kind="navigate", url="https://evil.example"), allowed
    )
    assert result.decision is PolicyDecision.DENY
    assert result.error_code is BrowseErrorCode.POLICY_DENIED


def test_subdomains_are_allowlisted_but_suffixes_are_not():
    assert is_allowed_url("https://api.tmsearch.uspto.gov", ["tmsearch.uspto.gov"])
    assert not is_allowed_url(
        "https://tmsearch.uspto.gov.evil.example", ["tmsearch.uspto.gov"]
    )


def test_allowlisted_hosts_require_https():
    allowed = ["tmsearch.uspto.gov"]
    assert not is_allowed_url("http://tmsearch.uspto.gov/search", allowed)
    assert is_allowed_url("https://tmsearch.uspto.gov/search", allowed)


def test_legal_agreement_requires_confirmation():
    result = authorize(BrowserAction(kind="accept_terms"), ["tmsearch.uspto.gov"])
    assert result.decision is PolicyDecision.CONFIRM
    assert result.error_code is BrowseErrorCode.CONFIRMATION_REQUIRED


def test_visual_target_requires_complete_artifact_bound_metadata():
    result = authorize(BrowserAction(kind="visual_target"), ["tmsearch.uspto.gov"])
    assert result.decision is PolicyDecision.DENY

    complete = BrowserAction(
        kind="visual_target",
        screenshot_artifact_id="screen-1",
        viewport_width=1280,
        viewport_height=720,
        x=640,
        y=360,
        uncertainty=0.1,
    )
    assert authorize(complete, ["tmsearch.uspto.gov"]).decision is PolicyDecision.ALLOW


@pytest.mark.parametrize(
    "host",
    ["google.com", "www.google.com", "bing.com", "duckduckgo.com", "search.brave.com"],
)
def test_search_discovery_admits_observed_destination(host):
    assert search_discovery_domain(
        f"https://{host}/search?q=recipe",
        "https://www.allrecipes.com/recipe/1",
        "https://allrecipes.com/recipe/1",
        [host],
    ) == "allrecipes.com"


@pytest.mark.parametrize(
    ("source", "href", "destination", "allowed"),
    [
        ("https://allrecipes.com/", "https://other.com/", "https://other.com/", ["allrecipes.com"]),
        ("https://www.google.com/", "https://other.com/", "https://other.com/", ["bing.com"]),
        ("https://google.com.evil.com/", "https://other.com/", "https://other.com/", ["evil.com"]),
        ("https://maps.google.com/", "https://other.com/", "https://other.com/", ["google.com"]),
        ("https://google.com/", None, "https://other.com/", ["google.com"]),
        ("https://google.com/", "https://recipe.com/", "https://evil.com/", ["google.com"]),
        ("https://google.com/", "https://google.com/url?q=https://evil.com/", "https://evil.com/", ["google.com"]),
        ("https://google.com/", "http://other.com/", "http://other.com/", ["google.com"]),
        ("https://google.com/", "https://127.0.0.1/", "https://127.0.0.1/", ["google.com"]),
        ("https://google.com/", "https://localhost/", "https://localhost/", ["google.com"]),
        ("https://google.com/", "https://user:pass@other.com/", "https://other.com/", ["google.com"]),
        ("https://google.com/", "https://other.com:8443/", "https://other.com:8443/", ["google.com"]),
        ("https://google.com/", "https://github.io/", "https://github.io/", ["google.com"]),
    ],
)
def test_search_discovery_rejects_unproven_or_invalid_destinations(
    source, href, destination, allowed
):
    assert search_discovery_domain(source, href, destination, allowed) is None
