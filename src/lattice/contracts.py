"""Versioned domain contracts for the content-production pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .config import ConfigError


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class Topic:
    title: str
    subject_area: str

    def __post_init__(self) -> None:
        _text(self.title, "topic.title")
        _text(self.subject_area, "topic.subject_area")

    @property
    def key(self) -> str:
        return re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()


@dataclass(frozen=True)
class Source:
    title: str
    citation: str
    url: str
    source_type: str

    def __post_init__(self) -> None:
        for field in ("title", "citation", "url", "source_type"):
            _text(getattr(self, field), f"source.{field}")


@dataclass(frozen=True)
class Claim:
    statement: str
    evidence_level: str
    source_indices: tuple[int, ...]
    uncertainty: str = ""

    def __post_init__(self) -> None:
        _text(self.statement, "claim.statement")
        _text(self.evidence_level, "claim.evidence_level")
        if any(index < 0 for index in self.source_indices):
            raise ConfigError("claim.source_indices cannot contain negative values.")


@dataclass(frozen=True)
class ResearchPacket:
    topic: Topic
    summary: str
    sources: tuple[Source, ...]
    claims: tuple[Claim, ...]
    created_at: str
    version: int = 1

    def __post_init__(self) -> None:
        _text(self.summary, "research.summary")
        if not self.sources:
            raise ConfigError("research.sources must contain at least one source.")
        if not self.claims:
            raise ConfigError("research.claims must contain at least one claim.")
        if self.version < 1:
            raise ConfigError("research.version must be positive.")
        for claim in self.claims:
            if any(index >= len(self.sources) for index in claim.source_indices):
                raise ConfigError(
                    f"Claim has a source index outside the {len(self.sources)} sources."
                )


@dataclass(frozen=True)
class ScriptSection:
    heading: str
    text: str

    def __post_init__(self) -> None:
        _text(self.heading, "script_section.heading")
        _text(self.text, "script_section.text")


@dataclass(frozen=True)
class Script:
    topic: Topic
    sections: tuple[ScriptSection, ...]
    estimated_duration_seconds: int
    source_claim_count: int
    version: int = 1

    def __post_init__(self) -> None:
        if not self.sections:
            raise ConfigError("script.sections must contain at least one section.")
        if self.estimated_duration_seconds < 1:
            raise ConfigError("script.estimated_duration_seconds must be positive.")
        if self.source_claim_count < 1:
            raise ConfigError("script.source_claim_count must be positive.")
        if self.version < 1:
            raise ConfigError("script.version must be positive.")


class EpisodeStatus(str, Enum):
    """Lifecycle states visible to workers and the authenticated review app."""

    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ReviewDecision(str, Enum):
    """The only decisions a reviewer can make on a final video."""

    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class Episode:
    """A reviewable video version and its durable processing identity."""

    id: str
    topic: Topic
    status: EpisodeStatus
    revision: int
    final_video_uri: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        _text(self.id, "episode.id")
        if self.revision < 1:
            raise ConfigError("episode.revision must be positive.")
        if self.status == EpisodeStatus.AWAITING_REVIEW and not self.final_video_uri:
            raise ConfigError(
                "episode.final_video_uri is required when awaiting review."
            )


@dataclass(frozen=True)
class Review:
    """An immutable decision made by the authenticated owner."""

    episode_id: str
    decision: ReviewDecision
    reviewer_id: str
    feedback: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        _text(self.episode_id, "review.episode_id")
        _text(self.reviewer_id, "review.reviewer_id")
        if self.decision == ReviewDecision.REJECT and not self.feedback.strip():
            raise ConfigError("review.feedback is required when rejecting a video.")


def now_utc() -> str:
    """Return a stable, serializable UTC timestamp for artifact provenance."""

    return datetime.now(timezone.utc).isoformat()
