"""Deterministic authorization rules for read-only browser automation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from lexoid.core.browse.schemas import BrowserAction, BrowseErrorCode


class PolicyDecision(str, Enum):
    """Authorization result ordered by safety precedence."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyResult:
    """Deterministic result of authorizing an action."""

    decision: PolicyDecision
    reason: str
    error_code: BrowseErrorCode | None = None


_DENIED_ACTIONS = {"upload", "purchase", "book", "apply", "login_submit"}
_CONFIRM_ACTIONS = {"accept_terms"}
_READ_ONLY_ACTIONS = {
    "click",
    "type",
    "select",
    "keypress",
    "hover",
    "scroll",
    "navigate",
    "back",
    "refresh",
    "wait",
    "done",
    "visual_target",
}
_DENIED_TEXT_MARKERS = ("password", "passcode", "credential", "credit card")


def normalize_domain(value: str) -> str:
    """Normalize a hostname or URL for deterministic allowlist comparison."""
    parsed = urlparse(value if "://" in value else f"//{value}")
    return (parsed.hostname or "").lower().rstrip(".")


def is_allowed_url(url: str, allowed_domains: list[str]) -> bool:
    """Return whether a URL host is on an exact or subdomain allowlist entry."""
    host = normalize_domain(url)
    return bool(host) and any(
        host == domain or host.endswith(f".{domain}")
        for domain in (normalize_domain(item) for item in allowed_domains)
        if domain
    )


def authorize(action: BrowserAction, allowed_domains: list[str]) -> PolicyResult:
    """Authorize one action using ``deny > confirm > allow > default``."""
    if action.kind in _DENIED_ACTIONS:
        return PolicyResult(
            PolicyDecision.DENY, "read-only policy", BrowseErrorCode.POLICY_DENIED
        )
    if action.kind in _CONFIRM_ACTIONS:
        return PolicyResult(
            PolicyDecision.CONFIRM,
            "legal agreement",
            BrowseErrorCode.CONFIRMATION_REQUIRED,
        )
    if (
        action.kind == "type"
        and action.text
        and any(marker in action.text.lower() for marker in _DENIED_TEXT_MARKERS)
    ):
        return PolicyResult(
            PolicyDecision.DENY,
            "possible credential entry",
            BrowseErrorCode.POLICY_DENIED,
        )
    if action.kind == "navigate":
        if not action.url or not is_allowed_url(action.url, allowed_domains):
            return PolicyResult(
                PolicyDecision.DENY,
                "destination outside allowlist",
                BrowseErrorCode.POLICY_DENIED,
            )
    if action.kind == "visual_target":
        visual_fields = (
            action.screenshot_artifact_id,
            action.viewport_width,
            action.viewport_height,
            action.x,
            action.y,
            action.uncertainty,
        )
        if any(value is None for value in visual_fields):
            return PolicyResult(
                PolicyDecision.DENY,
                "incomplete visual target",
                BrowseErrorCode.POLICY_DENIED,
            )
    if action.kind in _READ_ONLY_ACTIONS:
        return PolicyResult(PolicyDecision.ALLOW, "read-only action")
    return PolicyResult(
        PolicyDecision.DENY, "unknown action", BrowseErrorCode.POLICY_DENIED
    )
