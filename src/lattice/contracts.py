"""Versioned domain contracts for the content-production pipeline."""

from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .config import ConfigError


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string.")
    return value.strip()


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ArtifactProvenance:
    """Portable provenance shared by every persisted pipeline artifact."""

    artifact_id: str
    artifact_version: int = 1
    config_version: str = ""
    config_hash: str = ""
    prompt_version: str = ""
    provider_model: str = ""
    input_artifact_ids: tuple[str, ...] = ()
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    approval_state: ApprovalState = ApprovalState.PENDING

    def __post_init__(self) -> None:
        _text(self.artifact_id, "provenance.artifact_id")
        if not isinstance(self.artifact_version, int) or self.artifact_version < 1:
            raise ConfigError("provenance.artifact_version must be positive.")
        for field in ("config_version", "config_hash", "prompt_version", "provider_model"):
            value = getattr(self, field)
            if value and not isinstance(value, str):
                raise ConfigError(f"provenance.{field} must be a string.")
        if any(not isinstance(value, str) or not value.strip() for value in self.input_artifact_ids):
            raise ConfigError("provenance.input_artifact_ids must contain non-empty strings.")
        if self.content_hash and not re.fullmatch(r"[0-9a-f]{64}", self.content_hash):
            raise ConfigError("provenance.content_hash must be a lowercase SHA-256 hash.")

    @classmethod
    def for_content(cls, artifact_id: str, content: object, **kwargs: object) -> "ArtifactProvenance":
        serialized = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        timestamp = kwargs.pop("created_at", "") or now_utc()
        return cls(
            artifact_id=artifact_id,
            content_hash=digest,
            created_at=timestamp,
            updated_at=kwargs.pop("updated_at", timestamp),
            **kwargs,
        )


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
    provenance: ArtifactProvenance | None = None

    def __post_init__(self) -> None:
        if not self.sections:
            raise ConfigError("script.sections must contain at least one section.")
        if self.estimated_duration_seconds < 1:
            raise ConfigError("script.estimated_duration_seconds must be positive.")
        if not isinstance(self.source_claim_count, int) or self.source_claim_count < 1:
            raise ConfigError("script.source_claim_count must be positive.")
        if not isinstance(self.version, int) or self.version < 1:
            raise ConfigError("script.version must be positive.")


@dataclass(frozen=True)
class StoryboardScene:
    scene_id: str
    script_section_heading: str
    narration: str
    visual_direction: str
    duration_seconds: int

    def __post_init__(self) -> None:
        for field in ("scene_id", "script_section_heading", "narration", "visual_direction"):
            _text(getattr(self, field), f"storyboard_scene.{field}")
        if self.duration_seconds < 1:
            raise ConfigError("storyboard_scene.duration_seconds must be positive.")


@dataclass(frozen=True)
class Storyboard:
    scenes: tuple[StoryboardScene, ...]
    version: int = 1
    provenance: ArtifactProvenance | None = None

    def __post_init__(self) -> None:
        if not self.scenes:
            raise ConfigError("storyboard.scenes must contain at least one scene.")
        if not isinstance(self.version, int) or self.version < 1:
            raise ConfigError("storyboard.version must be positive.")
        if len({scene.scene_id for scene in self.scenes}) != len(self.scenes):
            raise ConfigError("storyboard scene IDs must be unique.")


@dataclass(frozen=True)
class AssetReference:
    asset_id: str
    asset_type: str
    uri: str

    def __post_init__(self) -> None:
        for field in ("asset_id", "asset_type", "uri"):
            _text(getattr(self, field), f"asset.{field}")


@dataclass(frozen=True)
class AssetManifest:
    assets: tuple[AssetReference, ...]
    version: int = 1
    provenance: ArtifactProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or self.version < 1:
            raise ConfigError("asset_manifest.version must be positive.")
        if not self.assets:
            raise ConfigError("asset_manifest.assets must contain at least one asset.")
        if len({asset.asset_id for asset in self.assets}) != len(self.assets):
            raise ConfigError("asset_manifest asset IDs must be unique.")


class RenderJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class RenderJob:
    job_id: str
    storyboard: Storyboard
    asset_manifest: AssetManifest
    status: RenderJobStatus = RenderJobStatus.QUEUED
    version: int = 1
    provenance: ArtifactProvenance | None = None

    def __post_init__(self) -> None:
        _text(self.job_id, "render_job.job_id")
        if not isinstance(self.version, int) or self.version < 1:
            raise ConfigError("render_job.version must be positive.")

    def transition_to(self, status: RenderJobStatus) -> "RenderJob":
        allowed = {
            RenderJobStatus.QUEUED: (RenderJobStatus.RUNNING, RenderJobStatus.FAILED),
            RenderJobStatus.RUNNING: (RenderJobStatus.SUCCEEDED, RenderJobStatus.FAILED),
            RenderJobStatus.SUCCEEDED: (),
            RenderJobStatus.FAILED: (),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"Cannot transition render job from {self.status.value} to {status.value}.")
        return RenderJob(
            job_id=self.job_id,
            storyboard=self.storyboard,
            asset_manifest=self.asset_manifest,
            status=status,
            version=self.version,
            provenance=self.provenance,
        )


@dataclass(frozen=True)
class PublishedVideo:
    video_id: str
    render_job_id: str
    uri: str
    approval_state: ApprovalState = ApprovalState.PENDING
    version: int = 1
    provenance: ArtifactProvenance | None = None

    def __post_init__(self) -> None:
        for field in ("video_id", "render_job_id", "uri"):
            _text(getattr(self, field), f"published_video.{field}")
        if not isinstance(self.version, int) or self.version < 1:
            raise ConfigError("published_video.version must be positive.")
        if self.approval_state == ApprovalState.APPROVED and not self.uri:
            raise ConfigError("published_video.uri is required when approved.")

    def transition_to(self, approval_state: ApprovalState) -> "PublishedVideo":
        allowed = {
            ApprovalState.PENDING: (ApprovalState.APPROVED, ApprovalState.REJECTED),
            ApprovalState.APPROVED: (),
            ApprovalState.REJECTED: (ApprovalState.PENDING,),
        }
        if approval_state not in allowed[self.approval_state]:
            raise ValueError(
                "Cannot transition published video from "
                f"{self.approval_state.value} to {approval_state.value}."
            )
        return PublishedVideo(
            video_id=self.video_id,
            render_job_id=self.render_job_id,
            uri=self.uri,
            approval_state=approval_state,
            version=self.version,
            provenance=self.provenance,
        )


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
