import unittest

from lattice.persistence import EpisodeRepository
from lattice.worker import LocalWorker


class WorkerTests(unittest.TestCase):
    def test_worker_retries_then_dead_letters(self) -> None:
        repository = EpisodeRepository()
        repository.enqueue_job("job", "render", "episode:v1")
        worker = LocalWorker(repository, {"render": lambda job: (_ for _ in ()).throw(RuntimeError("bad"))}, max_attempts=1)
        result = worker.run_once()
        self.assertEqual(result.status, "failed")
        self.assertEqual(repository.audit_events("job")[0]["event_type"], "job.failed")
        repository.close()
