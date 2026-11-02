"""Review queue rules for the future authenticated browser application."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import Episode, EpisodeStatus, Review, ReviewDecision, ReviewMarker, now_utc


@dataclass(frozen=True)
class QueueItem:
    """A queued episode with an ordering priority and optional rejection context."""

    episode: Episode
    feedback: str = ""


class ReviewQueue:
    """In-memory queue enforcing rejection priority and review transitions.

    Persistence and authentication belong to the server/API layer. This class
    keeps the domain rule testable without introducing a web framework early.
    """

    def __init__(self) -> None:
        self._items: list[QueueItem] = []
        self._reviews: list[Review] = []

    def enqueue(self, episode: Episode, feedback: str = "") -> None:
        if episode.status not in (EpisodeStatus.QUEUED, EpisodeStatus.REJECTED):
            raise ValueError("Only queued or rejected episodes can enter processing.")
        item = QueueItem(episode=episode, feedback=feedback)
        if episode.status == EpisodeStatus.REJECTED:
            self._items.insert(0, item)
        else:
            self._items.append(item)

    def next(self) -> QueueItem:
        if not self._items:
            raise LookupError("The processing queue is empty.")
        return self._items.pop(0)

    def submit_for_review(self, episode: Episode, final_video_uri: str) -> Episode:
        updated = Episode(
            id=episode.id,
            topic=episode.topic,
            status=EpisodeStatus.AWAITING_REVIEW,
            revision=episode.revision,
            final_video_uri=final_video_uri,
            created_at=episode.created_at or now_utc(),
        )
        return updated

    def decide(
        self,
        episode: Episode,
        reviewer_id: str,
        decision: ReviewDecision,
        feedback: str = "",
        criteria: tuple[str, ...] = (),
        markers: tuple[ReviewMarker, ...] = (),
    ) -> tuple[Episode, Review]:
        if episode.status != EpisodeStatus.AWAITING_REVIEW:
            raise ValueError("Only episodes awaiting review can receive a decision.")
        review = Review(
            episode_id=episode.id,
            decision=decision,
            reviewer_id=reviewer_id,
            feedback=feedback,
            criteria=criteria,
            markers=markers,
            created_at=now_utc(),
        )
        next_status = (
            EpisodeStatus.APPROVED
            if decision == ReviewDecision.APPROVE
            else EpisodeStatus.REJECTED
        )
        updated = Episode(
            id=episode.id,
            topic=episode.topic,
            status=next_status,
            revision=episode.revision + (1 if decision == ReviewDecision.REJECT else 0),
            final_video_uri=episode.final_video_uri,
            created_at=episode.created_at or now_utc(),
        )
        self._reviews.append(review)
        if decision == ReviewDecision.REJECT:
            self.enqueue(updated, feedback)
        return updated, review

    @property
    def reviews(self) -> tuple[Review, ...]:
        return tuple(self._reviews)
