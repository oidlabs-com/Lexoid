"""Deterministic authorization rules for read-only browser automation."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from lexoid.core.browse.schemas import BrowseErrorCode, BrowserAction


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
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

PUBLIC_SUFFIXES = {
    "com",
    "org",
    "net",
    "edu",
    "gov",
    "mil",
    "int",
    "io",
    "ai",
    "co",
    "us",
    "uk",
    "ca",
    "co.uk",
    "gov.uk",
    "org.uk",
    "com.au",
    "net.au",
    "org.au",
    "gc.ca",
}
SHARED_HOSTING_DOMAINS = {
    "github.io",
    "gitlab.io",
    "blogspot.com",
    "wordpress.com",
    "vercel.app",
    "netlify.app",
    "pages.dev",
    "s3.amazonaws.com",
    "azurewebsites.net",
}

_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\[\]{}|\\^`]+")
_DOMAIN_TLDS = (
    "gov.uk",
    "co.uk",
    "org.uk",
    "com.au",
    "net.au",
    "org.au",
    "gc.ca",
    "gov",
    "com",
    "org",
    "net",
    "edu",
    "mil",
    "int",
    "io",
    "ai",
    "co",
    "us",
    "uk",
    "ca",
)
_DOMAIN_TLD_PATTERN = "|".join(re.escape(tld) for tld in _DOMAIN_TLDS)
_DOMAIN_PATTERN = re.compile(
    rf"(?<![@a-zA-Z0-9_.-])"
    rf"((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{{0,61}}[a-zA-Z0-9])?\.)+(?:{_DOMAIN_TLD_PATTERN}))"
    r"(/[^\s\"'<>\[\]{}|\\^`]*)?",
    re.IGNORECASE,
)


def _is_ip_or_localhost(host: str) -> bool:
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_seed_url(url: str) -> str:
    """Validate and normalize a seed URL, requiring secure HTTPS."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("seed URL must be a non-empty string")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError(
            f"seed URL must use https scheme, got: {parsed.scheme or 'none'}"
        )
    if parsed.username or parsed.password:
        raise ValueError("seed URL must not contain embedded credentials")
    if parsed.port and parsed.port != 443:
        raise ValueError(f"unsupported port in seed URL: {parsed.port}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("seed URL must include a valid hostname")
    if _is_ip_or_localhost(host):
        raise ValueError(f"seed URL cannot target IP address or localhost: {host}")
    labels = host.split(".")
    if len(labels) < 2:
        raise ValueError(f"seed hostname must have at least two labels: {host}")
    if host in PUBLIC_SUFFIXES or host in SHARED_HOSTING_DOMAINS:
        raise ValueError(
            f"seed hostname cannot be a public suffix or shared hosting domain: {host}"
        )
    for label in labels:
        if not label or len(label) > 63:
            raise ValueError(f"invalid domain label length in {host}: {label}")
        if not _DOMAIN_LABEL_RE.match(label):
            raise ValueError(f"invalid characters in domain label: {label}")
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://{host}{path}{query}"


def extract_query_sources(query: str) -> list[str]:
    """Extract explicit HTTPS URLs and literal domains from user query text."""
    results: list[str] = []
    seen: set[str] = set()
    url_spans: list[tuple[int, int]] = []

    for match in _URL_PATTERN.finditer(query):
        raw = match.group(0).rstrip(".,;:!?)'\"")
        try:
            validated = validate_seed_url(raw)
            if validated not in seen:
                seen.add(validated)
                results.append(validated)
            url_spans.append((match.start(), match.start() + len(raw)))
        except ValueError:
            continue

    for match in _DOMAIN_PATTERN.finditer(query):
        m_start = match.start()
        # Avoid matching domain inside an already extracted full URL
        if any(start <= m_start and m_start < end for start, end in url_spans):
            continue
        host = match.group(1).lower().rstrip(".")
        path = (match.group(2) or "").rstrip(".,;:!?)'\"")
        candidate = f"https://{host}{path or '/'}"
        try:
            validated = validate_seed_url(candidate)
            if validated not in seen:
                seen.add(validated)
                results.append(validated)
        except ValueError:
            continue

    return results


def derive_allowed_domains(urls_or_hosts: list[str]) -> list[str]:
    """Derive deduplicated allowlist domains with www prefix stripped."""
    domains: list[str] = []
    seen: set[str] = set()
    for item in urls_or_hosts:
        if not item:
            continue
        host = normalize_domain(item)
        if host.startswith("www.") and len(host) > 4:
            host = host[4:]
        if (
            host in PUBLIC_SUFFIXES
            or host in SHARED_HOSTING_DOMAINS
            or len(host.split(".")) < 2
        ):
            continue
        if host and host not in seen:
            seen.add(host)
            domains.append(host)
    return domains


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
