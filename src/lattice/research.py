"""Provider-neutral research interfaces and evidence validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import ResearchPacket, Topic


class ResearchProvider(Protocol):
    """Capability required to replace the local provisional research adapter."""

    def research(self, topic: Topic) -> ResearchPacket:
        """Return a source-linked research packet for a topic."""


@dataclass(frozen=True)
class ResearchIssue:
    """A claim or source problem that blocks publication."""

    code: str
    message: str
    claim_index: int | None = None


def validate_research(packet: ResearchPacket) -> tuple[ResearchIssue, ...]:
    """Check claim/source integrity and reject provisional evidence."""

    issues: list[ResearchIssue] = []
    for index, claim in enumerate(packet.claims):
        if claim.evidence_level.strip().lower() in {"unverified", "placeholder"}:
            issues.append(
                ResearchIssue(
                    "unverified-claim",
                    "Claim evidence is provisional and must be replaced.",
                    index,
                )
            )
        if not claim.source_indices:
            issues.append(
                ResearchIssue(
                    "missing-source",
                    "Every claim must reference at least one source.",
                    index,
                )
            )
    if any(source.source_type.strip().lower() == "placeholder" for source in packet.sources):
        issues.append(
            ResearchIssue(
                "placeholder-source",
                "Placeholder sources are not publication-ready.",
            )
        )
    return tuple(issues)


def require_verified_research(packet: ResearchPacket) -> None:
    """Raise a clear error when research cannot enter a production stage."""

    issues = validate_research(packet)
    if issues:
        raise ValueError("; ".join(issue.message for issue in issues))
