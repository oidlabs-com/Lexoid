"""Deterministic, bounded view of a saved browse() run for the rubric judge.

A raw run record repeats the trace and embeds every captured page in full, which
can exceed a judge's context window. The view keeps the answer, outcome, every
claim, and a compact record of every browser action, and reduces each captured
page to labelled excerpts around claim quotes and rubric terms.
"""

from __future__ import annotations

import re
from typing import Any

EXCERPT_RADIUS = 300
# Budget for rubric-term windows; claim-quote windows are always kept.
PAGE_EXCERPT_CHARS = 4_000
PAGE_HEAD_CHARS = 500
MAX_URL_CHARS = 300
# Terms this frequent on a page mark navigation chrome, not distinguishing evidence.
MAX_TERM_HITS = 20
_STOPWORDS = frozenset(
    "about after agent along also being both browser can confirm confirmed correctly "
    "does each either evidence found from grader have including indicating inspect "
    "into open opened page pages relevant reported review shows side that their "
    "them there these this visible visibly were what when whether which while with "
    "within".split()
)


def build_judge_view(record: dict[str, Any], rubrics: dict[str, Any]) -> dict[str, Any]:
    """Return the evidence the judge sees for every rubric of one task."""
    result = record.get("result") or {}
    task_results = result.get("task_results") or []
    terms = _rubric_terms(rubrics)
    return {
        "view": (
            "Compact Lexoid run view. Page text is excerpted, not complete; "
            f"URLs longer than {MAX_URL_CHARS} chars are shortened."
        ),
        "task_id": record.get("task_id"),
        "status": record.get("status"),
        "error": record.get("error"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "answer": result.get("answer"),
        "warnings": result.get("warnings", []),
        "outcomes": [_outcome(item) for item in task_results],
        "claims": [
            _pick(claim, "claim_id", "text", "quote", "artifact_id")
            for item in task_results
            for claim in item.get("claims", [])
        ],
        "pages": [
            _page(artifact, _claim_quotes(item, artifact), terms)
            for item in task_results
            for artifact in item.get("artifacts", [])
        ],
        "actions": [
            _action(index, event)
            for index, event in enumerate(record.get("events") or [])
            if event.get("event") == "action"
        ],
    }


def _outcome(task_result: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        task_result,
        "status",
        "navigation_outcome",
        "coverage",
        "retained_tabs",
        "open_tabs_at_end",
    )


def _page(
    artifact: dict[str, Any], quotes: list[str], terms: list[str]
) -> dict[str, Any]:
    text = artifact.get("text") or ""
    return {
        "artifact_id": artifact.get("artifact_id"),
        "url": _shorten(artifact.get("url")),
        "tab_id": artifact.get("tab_id"),
        "captured_chars": len(text),
        "capture_truncated": artifact.get("truncated", False),
        "media_state": artifact.get("media_state"),
        "excerpts": _excerpts(text, quotes, terms),
    }


def _action(index: int, event: dict[str, Any]) -> dict[str, Any]:
    action = event.get("action") or {}
    result = event.get("result") or {}
    metadata = event.get("metadata") or {}
    return {
        "event_index": index,
        "tab_id": event.get("tab_id"),
        "operation": metadata.get("operation"),
        "action": metadata.get("description") or action.get("kind"),
        "success": result.get("success"),
        "outcome": result.get("outcome"),
        "error_code": result.get("error_code"),
        "url": _shorten(result.get("after_url")),
        "opened_tab_id": result.get("opened_tab_id"),
    }


def _excerpts(text: str, quotes: list[str], terms: list[str]) -> list[str]:
    """Page head and every claim quote, then rubric-term windows within a budget."""
    lowered = text.lower()
    spans = [(0, min(len(text), PAGE_HEAD_CHARS))]
    spans += [
        _window(text, anchor)
        for anchor in (_find(lowered, quote.lower()) for quote in quotes)
        if anchor is not None
    ]
    budget = PAGE_EXCERPT_CHARS - _covered(spans)
    for term in terms:
        if budget <= 0:
            break
        if not 0 < lowered.count(term) <= MAX_TERM_HITS:
            continue
        span = _window(text, (lowered.find(term), len(term)))
        if any(span[0] >= kept[0] and span[1] <= kept[1] for kept in spans):
            continue
        spans.append(span)
        budget -= span[1] - span[0]
    return [text[start:end] for start, end in _merge(spans) if start < end]


def _window(text: str, anchor: tuple[int, int]) -> tuple[int, int]:
    start, length = anchor
    return (
        max(0, start - EXCERPT_RADIUS),
        min(len(text), start + length + EXCERPT_RADIUS),
    )


def _covered(spans: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in _merge(spans))


def _find(lowered: str, needle: str) -> tuple[int, int] | None:
    position = lowered.find(needle) if needle else -1
    return (position, len(needle)) if position >= 0 else None


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _claim_quotes(task_result: dict[str, Any], artifact: dict[str, Any]) -> list[str]:
    return [
        claim["quote"]
        for claim in task_result.get("claims", [])
        if claim.get("quote")
        and claim.get("artifact_id") == artifact.get("artifact_id")
    ]


def _rubric_terms(rubrics: dict[str, Any]) -> list[str]:
    words = re.findall(
        r"[a-z0-9][a-z0-9.\-]*[a-z0-9]",
        " ".join(
            f"{rubric['requirement']} {rubric['verification']}"
            for rubric in rubrics.values()
        ).lower(),
    )
    return list(
        dict.fromkeys(
            word
            for word in words
            if word not in _STOPWORDS
            and (len(word) >= 4 or any(char.isdigit() for char in word))
        )
    )


def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _shorten(url: str | None) -> str | None:
    if url is None or len(url) <= MAX_URL_CHARS:
        return url
    return url[:MAX_URL_CHARS] + "…"
