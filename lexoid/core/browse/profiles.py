"""Trusted site profiles that add guidance without granting new permissions."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from lexoid.core.browse.policy import normalize_domain


class SiteProfile(BaseModel):
    """Host-scoped navigation guidance and collection capabilities."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=128)
    version: int = Field(default=1, ge=1)
    hosts: list[str] = Field(min_length=1, max_length=50)
    task_types: list[str] = Field(default_factory=lambda: ["search"], max_length=5)
    guidance: list[str] = Field(default_factory=list, max_length=20)
    # Export support requires a download-capable executor, which does not exist yet.
    supports_export: bool = False


# Site knowledge is supplied by the caller; no site is special-cased here.
_BUILTIN_PROFILES: tuple[SiteProfile, ...] = ()


def find_profile(
    url: str, task_type: str, profiles: Sequence[SiteProfile] | None = None
) -> SiteProfile | None:
    """Return the trusted profile matching a seed URL host and task type."""
    host = normalize_domain(urlparse(url).hostname or "")
    if not host:
        return None
    for profile in _BUILTIN_PROFILES if profiles is None else profiles:
        if task_type not in profile.task_types:
            continue
        for candidate in profile.hosts:
            normalized = normalize_domain(candidate)
            if normalized and (host == normalized or host.endswith(f".{normalized}")):
                return profile
    return None
