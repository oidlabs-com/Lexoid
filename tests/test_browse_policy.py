"""Deterministic safety tests for Slice 1 browse policy."""

from lexoid.core.browse.policy import PolicyDecision, authorize, is_allowed_url
from lexoid.core.browse.schemas import BrowserAction, BrowseErrorCode


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
