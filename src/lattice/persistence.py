"""SQLite persistence adapter for episodes, queue state, and review history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .contracts import Episode, EpisodeStatus, Review, ReviewDecision, Topic, now_utc


class EpisodeRepository:
    """Persist reviewable episodes behind a database-neutral domain API.

    SQLite keeps local development dependency-free. The schema and method
    boundaries are intentionally compatible with a future PostgreSQL adapter.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def save(self, episode: Episode, queue_priority: int | None = None) -> None:
        priority = queue_priority
        if episode.status in (EpisodeStatus.QUEUED, EpisodeStatus.REJECTED) and priority is None:
            priority = self._next_priority()
        self._connection.execute(
            """
            INSERT INTO episodes
              (id, topic_title, subject_area, status, revision, final_video_uri,
               created_at, queue_priority, queue_feedback)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              topic_title = excluded.topic_title,
              subject_area = excluded.subject_area,
              status = excluded.status,
              revision = excluded.revision,
              final_video_uri = excluded.final_video_uri,
              created_at = excluded.created_at,
              queue_priority = excluded.queue_priority,
              queue_feedback = excluded.queue_feedback
            """,
            (
                episode.id,
                episode.topic.title,
                episode.topic.subject_area,
                episode.status.value,
                episode.revision,
                episode.final_video_uri,
                episode.created_at or now_utc(),
                priority,
                "",
            ),
        )
        self._connection.commit()

    def get(self, episode_id: str) -> Episode | None:
        row = self._connection.execute(
            "SELECT * FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        return _episode_from_row(row) if row else None

    def claim_next(self) -> Episode:
        """Atomically claim the highest-priority queued episode."""

        with self._connection:
            row = self._connection.execute(
                """
                SELECT * FROM episodes
                WHERE status IN (?, ?)
                ORDER BY queue_priority ASC, created_at ASC
                LIMIT 1
                """,
                (EpisodeStatus.QUEUED.value, EpisodeStatus.REJECTED.value),
            ).fetchone()
            if row is None:
                raise LookupError("The processing queue is empty.")
            self._connection.execute(
                """
                UPDATE episodes
                SET status = ?, queue_priority = NULL
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    EpisodeStatus.PROCESSING.value,
                    row["id"],
                    EpisodeStatus.QUEUED.value,
                    EpisodeStatus.REJECTED.value,
                ),
            )
        claimed = self.get(row["id"])
        if claimed is None:
            raise RuntimeError("Queued episode disappeared while being claimed.")
        return claimed

    def submit_for_review(self, episode: Episode, final_video_uri: str) -> Episode:
        if episode.status != EpisodeStatus.PROCESSING:
            raise ValueError("Only processing episodes can be submitted for review.")
        updated = Episode(
            id=episode.id,
            topic=episode.topic,
            status=EpisodeStatus.AWAITING_REVIEW,
            revision=episode.revision,
            final_video_uri=final_video_uri,
            created_at=episode.created_at or now_utc(),
        )
        self.save(updated)
        return updated

    def decide(
        self,
        episode: Episode,
        reviewer_id: str,
        decision: ReviewDecision,
        feedback: str = "",
    ) -> tuple[Episode, Review]:
        if episode.status != EpisodeStatus.AWAITING_REVIEW:
            raise ValueError("Only episodes awaiting review can receive a decision.")
        review = Review(
            episode_id=episode.id,
            decision=decision,
            reviewer_id=reviewer_id,
            feedback=feedback,
            created_at=now_utc(),
        )
        status = (
            EpisodeStatus.APPROVED
            if decision == ReviewDecision.APPROVE
            else EpisodeStatus.REJECTED
        )
        priority = self._front_priority() if decision == ReviewDecision.REJECT else None
        updated = Episode(
            id=episode.id,
            topic=episode.topic,
            status=status,
            revision=episode.revision,
            final_video_uri=episode.final_video_uri,
            created_at=episode.created_at or now_utc(),
        )
        with self._connection:
            self._connection.execute(
                """
                UPDATE episodes
                SET status = ?, queue_priority = ?, queue_feedback = ?
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    priority,
                    feedback,
                    episode.id,
                    EpisodeStatus.AWAITING_REVIEW.value,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO reviews
                  (episode_id, decision, reviewer_id, feedback, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    review.episode_id,
                    review.decision.value,
                    review.reviewer_id,
                    review.feedback,
                    review.created_at,
                ),
            )
        return updated, review

    def reviews_for(self, episode_id: str) -> tuple[Review, ...]:
        rows = self._connection.execute(
            "SELECT * FROM reviews WHERE episode_id = ? ORDER BY id", (episode_id,)
        ).fetchall()
        return tuple(
            Review(
                episode_id=row["episode_id"],
                decision=ReviewDecision(row["decision"]),
                reviewer_id=row["reviewer_id"],
                feedback=row["feedback"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS episodes (
              id TEXT PRIMARY KEY,
              topic_title TEXT NOT NULL,
              subject_area TEXT NOT NULL,
              status TEXT NOT NULL,
              revision INTEGER NOT NULL CHECK (revision > 0),
              final_video_uri TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              queue_priority INTEGER,
              queue_feedback TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS episodes_queue_idx
              ON episodes(status, queue_priority, created_at);
            CREATE TABLE IF NOT EXISTS reviews (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              episode_id TEXT NOT NULL REFERENCES episodes(id),
              decision TEXT NOT NULL,
              reviewer_id TEXT NOT NULL,
              feedback TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            """
        )

    def _next_priority(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(queue_priority), 0) + 1 FROM episodes"
        ).fetchone()
        return int(row[0])

    def _front_priority(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MIN(queue_priority), 0) - 1 FROM episodes WHERE status = ?",
            (EpisodeStatus.QUEUED.value,),
        ).fetchone()
        return int(row[0])


def _episode_from_row(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        topic=Topic(row["topic_title"], row["subject_area"]),
        status=EpisodeStatus(row["status"]),
        revision=row["revision"],
        final_video_uri=row["final_video_uri"],
        created_at=row["created_at"],
    )
