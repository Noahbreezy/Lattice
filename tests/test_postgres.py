"""Opt-in database contract test against a disposable PostgreSQL database."""

import os
import unittest
import uuid

from lattice.contracts import Episode, EpisodeStatus, ReviewDecision, Topic
from lattice.postgres import PostgresEpisodeRepository


@unittest.skipUnless(
    os.getenv("LATTICE_TEST_POSTGRES_URL"), "Set LATTICE_TEST_POSTGRES_URL"
)
class PostgresRepositoryTests(unittest.TestCase):
    def test_queue_review_revision_and_job_contract(self):
        repository = PostgresEpisodeRepository(os.environ["LATTICE_TEST_POSTGRES_URL"])
        episode_id = f"test-{uuid.uuid4().hex}"
        try:
            episode = Episode(
                episode_id, Topic("A topic", "systems"), EpisodeStatus.QUEUED, 1
            )
            repository.save(episode)
            repository.create_revision(episode_id, 1)
            processing = repository.claim_episode(episode_id)
            self.assertEqual(processing.status, EpisodeStatus.PROCESSING)
            awaiting = repository.submit_for_review(processing, "s3://test/video.mp4")
            self.assertEqual(
                repository.artifacts_for_revision(episode_id, 1).video_uri,
                "s3://test/video.mp4",
            )
            rejected, review = repository.decide(
                awaiting,
                "owner",
                ReviewDecision.REJECT,
                "Show the consequence sooner.",
                ("pacing",),
            )
            self.assertEqual(review.decision, ReviewDecision.REJECT)
            self.assertEqual(rejected.revision, 2)
            self.assertIn(episode_id, {item.id for item in repository.list_queue()})
            job = repository.enqueue_job(
                f"produce:{episode_id}:2", "produce", f"{episode_id}:2"
            )
            self.assertEqual(repository.claim_job("produce").id, job.id)
            self.assertEqual(repository.complete_job(job.id).status, "succeeded")
        finally:
            repository.close()
