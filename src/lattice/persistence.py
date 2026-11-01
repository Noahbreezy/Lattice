"""SQLite persistence adapter for episodes, queue state, and review history."""

from __future__ import annotations

import sqlite3
import hashlib
from pathlib import Path
from dataclasses import dataclass

from .contracts import Episode, EpisodeStatus, Review, ReviewDecision, Topic, now_utc


@dataclass(frozen=True)
class Job:
    """Durable work item suitable for a database-backed worker."""

    id: str
    kind: str
    idempotency_key: str
    status: str
    attempts: int
    payload: str
    error: str = ""
    lease_until: str = ""


class EpisodeRepository:
    """Persist reviewable episodes behind a database-neutral domain API.

    SQLite keeps local development dependency-free. The schema and method
    boundaries are intentionally compatible with a future PostgreSQL adapter.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
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

    def list_episodes(self) -> tuple[Episode, ...]:
        rows = self._connection.execute(
            "SELECT * FROM episodes ORDER BY created_at ASC, id ASC"
        ).fetchall()
        return tuple(_episode_from_row(row) for row in rows)

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
            cursor = self._connection.execute(
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
            if cursor.rowcount != 1:
                raise ValueError(
                    "The episode changed before this review decision was saved."
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

    def enqueue_job(self, job_id: str, kind: str, idempotency_key: str, payload: str = "") -> Job:
        """Insert a queued job, returning the existing job for duplicate requests."""

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO jobs (id, kind, idempotency_key, status, attempts, payload)
                VALUES (?, ?, ?, 'queued', 0, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (job_id, kind, idempotency_key, payload),
            )
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Job disappeared after enqueue.")
        return _job_from_row(row)

    def claim_job(self, kind: str | None = None) -> Job:
        """Atomically claim the oldest queued job and increment its attempt count."""

        with self._connection:
            query = "SELECT * FROM jobs WHERE status = 'queued'"
            params: tuple[str, ...] = ()
            if kind is not None:
                query += " AND kind = ?"
                params = (kind,)
            query += " ORDER BY created_at ASC LIMIT 1"
            row = self._connection.execute(query, params).fetchone()
            if row is None:
                raise LookupError("The job queue is empty.")
            self._connection.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, lease_until = datetime('now', '+15 minutes') WHERE id = ?",
                (row["id"],),
            )
        claimed = self._connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (row["id"],)
        ).fetchone()
        if claimed is None:
            raise RuntimeError("Job disappeared while being claimed.")
        return _job_from_row(claimed)

    def complete_job(self, job_id: str) -> Job:
        return self._update_job_status(job_id, "succeeded")

    def fail_job(self, job_id: str, error: str, retry: bool = True) -> Job:
        if not error.strip():
            raise ValueError("A job failure must include an error.")
        return self._update_job_status(job_id, "queued" if retry else "failed", error)

    def _update_job_status(self, job_id: str, status: str, error: str = "") -> Job:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE jobs SET status = ?, error = ? WHERE id = ? AND status = 'running'",
                (status, error, job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Job is not currently running or does not exist.")
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Job disappeared after update.")
        return _job_from_row(row)

    def heartbeat_job(self, job_id: str, lease_minutes: int = 15) -> Job:
        if lease_minutes < 1:
            raise ValueError("lease_minutes must be positive.")
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE jobs SET lease_until = datetime('now', ?) WHERE id = ? AND status = 'running'",
                (f"+{lease_minutes} minutes", job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Job is not currently running or does not exist.")
        return self._get_job(job_id)

    def recover_stale_jobs(self) -> tuple[Job, ...]:
        with self._connection:
            rows = self._connection.execute(
                "SELECT id FROM jobs WHERE status = 'running' AND lease_until < datetime('now')"
            ).fetchall()
            self._connection.execute(
                "UPDATE jobs SET status = 'queued', error = 'Worker lease expired', lease_until = '' "
                "WHERE status = 'running' AND lease_until < datetime('now')"
            )
        return tuple(self._get_job(row["id"]) for row in rows)

    def record_audit(self, event_type: str, subject_id: str, details: str = "") -> None:
        if not event_type.strip() or not subject_id.strip():
            raise ValueError("Audit event type and subject are required.")
        with self._connection:
            self._connection.execute(
                "INSERT INTO audit_events (event_type, subject_id, details, created_at) VALUES (?, ?, ?, ?)",
                (event_type, subject_id, details, now_utc()),
            )

    def audit_events(self, subject_id: str | None = None) -> tuple[dict[str, str], ...]:
        if subject_id is None:
            rows = self._connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM audit_events WHERE subject_id = ? ORDER BY id", (subject_id,)
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def _get_job(self, job_id: str) -> Job:
        row = self._connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise RuntimeError("Job disappeared after update.")
        return _job_from_row(row)

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
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              idempotency_key TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
              attempts INTEGER NOT NULL CHECK (attempts >= 0),
              payload TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              lease_until TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS jobs_queue_idx
              ON jobs(status, kind, created_at);
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              subject_id TEXT NOT NULL,
              details TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(jobs)")}
        if "lease_until" not in columns:
            self._connection.execute("ALTER TABLE jobs ADD COLUMN lease_until TEXT NOT NULL DEFAULT ''")
            self._connection.commit()

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


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        attempts=row["attempts"],
        payload=row["payload"],
        error=row["error"],
        lease_until=row["lease_until"],
    )
