"""Provider-neutral retention planning for generated video artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .config import RetentionSettings
from .contracts import EpisodeStatus


class StorageLocation(str, Enum):
    CLOUD = "cloud"
    SERVER = "server"


@dataclass(frozen=True)
class StoredVideo:
    """Metadata needed to decide whether a video should be retained."""

    id: str
    status: EpisodeStatus
    location: StorageLocation
    created_at: str


@dataclass(frozen=True)
class RetentionAction:
    """A deletion candidate; execution is deliberately separate and auditable."""

    video_id: str
    reason: str


def plan_retention(
    videos: tuple[StoredVideo, ...], settings: RetentionSettings
) -> tuple[RetentionAction, ...]:
    """Return oldest-first deletion candidates for configured count limits.

    The planner never deletes files. A later worker should inspect this plan,
    record an audit event, and delete only after verifying the artifact is not
    being processed or reviewed.
    """

    actions: dict[str, RetentionAction] = {}
    location_limits = {
        StorageLocation.CLOUD: settings.max_cloud_videos,
        StorageLocation.SERVER: settings.max_server_videos,
    }
    status_limits = {
        EpisodeStatus.APPROVED: settings.max_approved_videos,
        EpisodeStatus.REJECTED: settings.max_rejected_videos,
        EpisodeStatus.AWAITING_REVIEW: settings.max_awaiting_review_videos,
    }

    for location, limit in location_limits.items():
        _mark_excess(
            (video for video in videos if video.location == location),
            limit,
            f"{location.value} storage limit exceeded",
            actions,
        )
    for status, limit in status_limits.items():
        _mark_excess(
            (video for video in videos if video.status == status),
            limit,
            f"{status.value} retention limit exceeded",
            actions,
        )
    return tuple(actions.values())


def _mark_excess(
    candidates: Iterable[StoredVideo],
    limit: int | None,
    reason: str,
    actions: dict[str, RetentionAction],
) -> None:
    if limit is None:
        return
    ordered = sorted(candidates, key=lambda video: video.created_at)
    for video in ordered[: max(0, len(ordered) - limit)]:
        actions.setdefault(video.id, RetentionAction(video.id, reason))
