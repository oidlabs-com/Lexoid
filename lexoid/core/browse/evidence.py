"""Deterministic evidence validation for Slice 1 browse results."""

from __future__ import annotations

from lexoid.core.browse.schemas import EvidenceClaim, PageArtifact


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
