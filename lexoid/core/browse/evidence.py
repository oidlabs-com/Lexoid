"""Deterministic evidence validation for Slice 1 browse results."""

from __future__ import annotations

from lexoid.core.browse.schemas import (
    ConstraintCheck,
    EvidenceClaim,
    PageArtifact,
    TaskFilter,
)


def validate_claim(claim: EvidenceClaim, artifacts: list[PageArtifact]) -> bool:
    """Return whether a claim's exact quote exists in its declared artifact."""
    for artifact in artifacts:
        if artifact.artifact_id == claim.artifact_id:
            return artifact.url == claim.source_url and claim.quote in artifact.text
    return False


def validated_claims(
    claims: list[EvidenceClaim], artifacts: list[PageArtifact]
) -> list[EvidenceClaim]:
    """Keep only claims that resolve to an exact captured artifact excerpt."""
    return [claim for claim in claims if validate_claim(claim, artifacts)]


def _normalize(value: str) -> str:
    return " ".join(value.split()).lower()


def verify_constraints(
    filters: list[TaskFilter], claims: list[EvidenceClaim]
) -> list[ConstraintCheck]:
    """Check whether a filter's value appears in validated evidence quotes.

    This proves value presence, not the semantic relationship the filter names.
    """
    checks: list[ConstraintCheck] = []
    for item in filters:
        needle = _normalize(item.value)
        supporting = [
            claim.claim_id for claim in claims if needle in _normalize(claim.quote)
        ]
        checks.append(
            ConstraintCheck(
                field=item.field,
                value=item.value,
                verified=bool(supporting),
                supporting_claim_ids=supporting[:500],
            )
        )
    return checks
