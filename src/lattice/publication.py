"""Provider-neutral publication records and a local no-op adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import PublishedVideo


@dataclass(frozen=True)
class Publication:
    video_id: str
    platform: str
    status: str
    remote_id: str = ""
    error: str = ""


class Publisher(Protocol):
    def publish(self, video: PublishedVideo, title: str, description: str) -> Publication:
        """Publish an approved video through a configured platform adapter."""


class LocalPublisher:
    """Safe local substitute that records intent without contacting a platform."""

    def publish(self, video: PublishedVideo, title: str, description: str) -> Publication:
        if video.approval_state.value != "approved":
            raise ValueError("Only approved videos can be published.")
        return Publication(video.video_id, "local", "simulated", remote_id=video.video_id)
