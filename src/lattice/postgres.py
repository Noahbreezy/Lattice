"""PostgreSQL repository adapter for the server deployment."""

from __future__ import annotations

import threading
from typing import Any

from .contracts import EpisodeStatus
from .persistence import EpisodeRepository, Job, _episode_from_row, _job_from_row


class _Connection:
    """Keep the repository's SQL boundary while adapting psycopg transactions."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Install lattice-video[server] for PostgreSQL support."
            ) from exc
        self.raw = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.lock = threading.RLock()
        self.transaction = None

    def execute(self, sql: str, params: tuple[Any, ...] = ()):
        with self.lock:
            return self.raw.execute(sql.replace("?", "%s"), params)

    def commit(self) -> None:
        # Outside explicit transaction blocks the connection is autocommit.
        pass

    def close(self) -> None:
        self.raw.close()

    def __enter__(self):
        self.lock.acquire()
        try:
            self.transaction = self.raw.transaction()
            self.transaction.__enter__()
        except Exception:
            self.transaction = None
            self.lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self.transaction.__exit__(exc_type, exc, traceback)
        finally:
            self.transaction = None
            self.lock.release()


class PostgresEpisodeRepository(EpisodeRepository):
    """Use the domain repository contract with atomic PostgreSQL jobs and reviews."""

    def __init__(self, dsn: str) -> None:
        self._connection = _Connection(dsn)
        self._create_schema()

    def _create_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, topic_title TEXT NOT NULL, subject_area TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL CHECK (revision > 0),
                final_video_uri TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                lesson_uri TEXT NOT NULL DEFAULT '', script_uri TEXT NOT NULL DEFAULT '',
                queue_priority INTEGER, queue_feedback TEXT NOT NULL DEFAULT '')""",
            "CREATE INDEX IF NOT EXISTS episodes_queue_idx ON episodes(status, queue_priority, created_at)",
            """CREATE TABLE IF NOT EXISTS reviews (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                episode_id TEXT NOT NULL REFERENCES episodes(id), decision TEXT NOT NULL,
                reviewer_id TEXT NOT NULL, feedback TEXT NOT NULL DEFAULT '',
                criteria TEXT NOT NULL DEFAULT '[]', markers TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS revisions (
                episode_id TEXT NOT NULL REFERENCES episodes(id),
                revision INTEGER NOT NULL CHECK (revision > 0), parent_revision INTEGER,
                reason TEXT NOT NULL, feedback TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                PRIMARY KEY (episode_id, revision))""",
            """CREATE TABLE IF NOT EXISTS revision_artifacts (
                episode_id TEXT NOT NULL REFERENCES episodes(id),
                revision INTEGER NOT NULL CHECK (revision > 0),
                video_uri TEXT NOT NULL, lesson_uri TEXT NOT NULL DEFAULT '',
                script_uri TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (episode_id, revision))""",
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
                attempts INTEGER NOT NULL CHECK (attempts >= 0), payload TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '', lease_until TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))""",
            "CREATE INDEX IF NOT EXISTS jobs_queue_idx ON jobs(status, kind, created_at)",
            """CREATE TABLE IF NOT EXISTS audit_events (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                event_type TEXT NOT NULL, subject_id TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""",
        )
        with self._connection:
            for statement in statements:
                self._connection.execute(statement)

    def _next_priority(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(queue_priority), 0) + 1 AS value FROM episodes"
        ).fetchone()
        return int(row["value"])

    def _front_priority(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MIN(queue_priority), 0) - 1 AS value FROM episodes WHERE status = ?",
            (EpisodeStatus.QUEUED.value,),
        ).fetchone()
        return int(row["value"])

    def claim_next(self):
        with self._connection:
            row = self._connection.execute(
                "SELECT * FROM episodes WHERE status IN (?, ?) "
                "ORDER BY queue_priority ASC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
                (EpisodeStatus.QUEUED.value, EpisodeStatus.REJECTED.value),
            ).fetchone()
            if row is None:
                raise LookupError("The processing queue is empty.")
            self._connection.execute(
                "UPDATE episodes SET status = ?, queue_priority = NULL WHERE id = ?",
                (EpisodeStatus.PROCESSING.value, row["id"]),
            )
        return _episode_from_row(
            self._connection.execute(
                "SELECT * FROM episodes WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def claim_job(self, kind: str | None = None, job_id: str | None = None) -> Job:
        with self._connection:
            query = "SELECT * FROM jobs WHERE status = 'queued'"
            params: tuple[str, ...] = ()
            if kind is not None:
                query += " AND kind = ?"
                params = (kind,)
            if job_id is not None:
                query += " AND id = ?"
                params += (job_id,)
            query += " ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
            row = self._connection.execute(query, params).fetchone()
            if row is None:
                raise LookupError("The job queue is empty.")
            self._connection.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, "
                "lease_until = to_char((now() AT TIME ZONE 'UTC') + interval '15 minutes', "
                "'YYYY-MM-DD HH24:MI:SS') WHERE id = ?",
                (row["id"],),
            )
        return _job_from_row(
            self._connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def heartbeat_job(self, job_id: str, lease_minutes: int = 15) -> Job:
        if lease_minutes < 1:
            raise ValueError("lease_minutes must be positive.")
        cursor = self._connection.execute(
            "UPDATE jobs SET lease_until = to_char((now() AT TIME ZONE 'UTC') + "
            "(? * interval '1 minute'), 'YYYY-MM-DD HH24:MI:SS') "
            "WHERE id = ? AND status = 'running'",
            (lease_minutes, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Job is not currently running or does not exist.")
        return self._get_job(job_id)

    def recover_stale_jobs(self) -> tuple[Job, ...]:
        with self._connection:
            rows = self._connection.execute(
                "UPDATE jobs SET status = 'queued', error = 'Worker lease expired', "
                "lease_until = '' WHERE status = 'running' AND lease_until < "
                "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') "
                "RETURNING id"
            ).fetchall()
        return tuple(self._get_job(row["id"]) for row in rows)
