import tempfile
import unittest
from pathlib import Path

from lattice.persistence import EpisodeRepository
from lattice.publication import LocalPublisher
from lattice.storage import LocalObjectStorage


class OperationsTests(unittest.TestCase):
    def test_storage_copies_and_verifies_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"video")
            storage = LocalObjectStorage(Path(directory) / "objects")
            stored = storage.put_file("videos/one.mp4", source)
            self.assertTrue(storage.verify(stored))

    def test_job_lease_recovery_and_audit(self) -> None:
        repository = EpisodeRepository()
        repository.enqueue_job("job", "render", "episode:v1")
        job = repository.claim_job()
        heartbeat = repository.heartbeat_job(job.id)
        self.assertEqual(heartbeat.status, "running")
        repository._connection.execute(
            "UPDATE jobs SET lease_until = '2000-01-01T00:00:00Z' WHERE id = ?", (job.id,)
        )
        recovered = repository.recover_stale_jobs()
        self.assertEqual(recovered[0].status, "queued")
        repository.record_audit("job.recovered", job.id, "lease expired")
        self.assertEqual(len(repository.audit_events(job.id)), 1)
        repository.close()
