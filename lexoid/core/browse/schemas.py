"""Public, provider-neutral schemas for a single browse task."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class BrowseTerminalState(str, Enum):
    """Terminal status for a browse task."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    LIMIT_REACHED = "limit_reached"
    CANCELLED = "cancelled"
    CLARIFICATION_NEEDED = "clarification_needed"


class BrowseErrorCode(str, Enum):
    """Stable machine-readable executor errors."""

    STALE_REF = "stale_ref"
    TAB_GONE = "tab_gone"
    TARGET_COVERED = "target_covered"
    POLICY_DENIED = "policy_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    NAVIGATION_TIMEOUT = "navigation_timeout"
    MODEL_UNSUPPORTED = "model_unsupported"


class BrowseLimits(BaseModel):
    """Bounded resources available to one browse task."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=8, ge=1, le=100)
    max_pages: int = Field(default=5, ge=1, le=100)
    max_snapshot_chars: int = Field(default=20_000, ge=1_000, le=200_000)
    max_artifact_chars: int = Field(default=100_000, ge=1_000, le=2_000_000)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=300_000)


class ElementRef(BaseModel):
    """An element reference valid only for the originating snapshot and frame."""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=1, max_length=128)
    tab_id: str = Field(min_length=1, max_length=128)
    frame_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=256)
    role: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, max_length=1_000)
    tag: str | None = Field(default=None, max_length=64)
    ordinal: int | None = Field(default=None, ge=0)


class BrowserSnapshot(BaseModel):
    """Bounded accessibility-first page observation."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=128)
    tab_id: str = Field(min_length=1, max_length=128)
    page_revision: int = Field(ge=0)
    url: str = Field(min_length=1, max_length=8_192)
    title: str = Field(default="", max_length=2_000)
    elements: list[ElementRef] = Field(default_factory=list, max_length=500)
    truncated: bool = False
    content_hash: str = Field(min_length=1, max_length=128)


class BrowserAction(BaseModel):
    """A proposed browser operation validated before execution."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
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
        "accept_terms",
    ]
    snapshot_id: str | None = Field(default=None, max_length=128)
    ref: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=10_000)
    url: str | None = Field(default=None, max_length=8_192)
    reason: str | None = Field(default=None, max_length=1_000)
    screenshot_artifact_id: str | None = Field(default=None, max_length=128)
    viewport_width: int | None = Field(default=None, ge=1, le=20_000)
    viewport_height: int | None = Field(default=None, ge=1, le=20_000)
    x: int | None = Field(default=None, ge=0, le=20_000)
    y: int | None = Field(default=None, ge=0, le=20_000)
    uncertainty: float | None = Field(default=None, ge=0, le=1)


class BrowseUsage(BaseModel):
    """Normalized provider usage for browse work."""

    model_config = ConfigDict(extra="forbid")

    input: int = Field(default=0, ge=0)
    output: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class PageArtifact(BaseModel):
    """Captured, provenance-bearing page material."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=8_192)
    tab_id: str = Field(min_length=1, max_length=128)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = Field(min_length=1, max_length=128)
    text: str = Field(default="", max_length=2_000_000)
    truncated: bool = False


class EvidenceClaim(BaseModel):
    """A claim with an exact quote anchored in a captured artifact."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=10_000)
    quote: str = Field(min_length=1, max_length=20_000)
    artifact_id: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=8_192)


class OpenTab(BaseModel):
    """A Lexoid-owned retained page."""

    model_config = ConfigDict(extra="forbid")

    tab_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=256)
    url: str = Field(min_length=1, max_length=8_192)
    title: str = Field(default="", max_length=2_000)


class BrowserActionResult(BaseModel):
    """Typed result of a browser action."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    outcome: str = Field(max_length=1_000)
    error_code: BrowseErrorCode | None = None
    before_url: str = ""
    after_url: str = ""
    warnings: list[str] = Field(default_factory=list, max_length=100)
    usage: BrowseUsage = Field(default_factory=BrowseUsage)


class BrowserActionTrace(BaseModel):
    """Safe, structured record of one observation or action lifecycle event."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["observation", "action", "artifact", "warning", "terminal"]
    task_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tab_id: str | None = None
    snapshot_id: str | None = None
    action: BrowserAction | None = None
    result: BrowserActionResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowseTask(BaseModel):
    """Validated single-task input and execution state."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default="task-1", min_length=1, max_length=128)
    task_type: Literal["search", "navigate", "capture"] = "search"
    seed_urls: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=4_000)
    requested_facts: list[str] = Field(default_factory=list, max_length=100)
    completion_criteria: list[str] = Field(default_factory=list, max_length=20)
    allowed_domains: list[str] = Field(min_length=1, max_length=100)
    limits: BrowseLimits = Field(default_factory=BrowseLimits)
    retain_final_page: bool = True
    status: BrowseTerminalState | None = None
    warnings: list[str] = Field(default_factory=list, max_length=100)
    unanswered_questions: list[str] = Field(default_factory=list, max_length=100)


class BrowseRequest(BaseModel):
    """Public request shape used by adapters and future MCP tools."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    limits: BrowseLimits = Field(default_factory=BrowseLimits)


class BrowseTaskResult(BaseModel):
    """Result for a single task, shaped for Slice 2 expansion."""

    model_config = ConfigDict(extra="forbid")

    task: BrowseTask
    status: BrowseTerminalState
    artifacts: list[PageArtifact] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    trace: list[BrowserActionTrace] = Field(default_factory=list)
    retained_tabs: list[OpenTab] = Field(default_factory=list)
    usage: BrowseUsage = Field(default_factory=BrowseUsage)


class BrowseResult(BaseModel):
    """Grounded browse response, evidence, and task-level detail."""

    model_config = ConfigDict(extra="forbid")

    answer: str = ""
    task_results: list[BrowseTaskResult] = Field(default_factory=list, max_length=1)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    usage: BrowseUsage = Field(default_factory=BrowseUsage)
