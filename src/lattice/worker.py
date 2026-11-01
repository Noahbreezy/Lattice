"""Small synchronous worker loop for local development."""

from __future__ import annotations

from collections.abc import Callable

from .persistence import EpisodeRepository, Job


class LocalWorker:
    """Run durable jobs with bounded retries and audit events."""

    def __init__(
        self,
        repository: EpisodeRepository,
        handlers: dict[str, Callable[[Job], None]],
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive.")
        self.repository = repository
        self.handlers = handlers
        self.max_attempts = max_attempts

    def run_once(self, kind: str | None = None) -> Job | None:
        self.repository.recover_stale_jobs()
        try:
            job = self.repository.claim_job(kind)
        except LookupError:
            return None
        handler = self.handlers.get(job.kind)
        if handler is None:
            return self._fail(job, f"No handler registered for {job.kind}.")
        try:
            handler(job)
        except Exception as exc:
            return self._fail(job, str(exc))
        completed = self.repository.complete_job(job.id)
        self.repository.record_audit("job.succeeded", job.id, job.kind)
        return completed

    def _fail(self, job: Job, error: str) -> Job:
        retry = job.attempts < self.max_attempts
        failed = self.repository.fail_job(job.id, error or "Unknown worker failure.", retry)
        self.repository.record_audit(
            "job.retry" if retry else "job.failed",
            job.id,
            error or "Unknown worker failure.",
        )
        return failed
