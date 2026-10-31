import tempfile
import unittest
from pathlib import Path

from lattice.contracts import Episode, EpisodeStatus, ReviewDecision, Topic
from lattice.persistence import EpisodeRepository


class EpisodeRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = EpisodeRepository()
        self.topic = Topic("A useful concept", "systems")

    def tearDown(self) -> None:
        self.repository.close()

    def test_round_trips_episode_to_file_backed_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = EpisodeRepository(Path(directory) / "lattice.sqlite")
            episode = Episode("episode-1", self.topic, EpisodeStatus.QUEUED, 1)
            repository.save(episode)
            persisted = repository.get("episode-1")
            self.assertEqual(persisted.id, episode.id)
            self.assertEqual(persisted.topic, episode.topic)
            self.assertEqual(persisted.status, episode.status)
            self.assertGreater(len(persisted.created_at), 0)
            repository.close()

    def test_claiming_queue_is_persistent_and_atomic(self) -> None:
        self.repository.save(
            Episode("ordinary", self.topic, EpisodeStatus.QUEUED, 1)
        )
        rejected = Episode(
            "rejected", self.topic, EpisodeStatus.REJECTED, 2, "private://old.mp4"
        )
        self.repository.save(rejected, queue_priority=-1)
        first = self.repository.claim_next()
        second = self.repository.claim_next()
        self.assertEqual(first.id, "rejected")
        self.assertEqual(first.status, EpisodeStatus.PROCESSING)
        self.assertEqual(second.id, "ordinary")
        with self.assertRaises(LookupError):
            self.repository.claim_next()

    def test_rejection_is_atomic_and_requeued_first_with_feedback(self) -> None:
        episode = Episode(
            "episode-1",
            self.topic,
            EpisodeStatus.PROCESSING,
            1,
        )
        self.repository.save(episode)
        awaiting = self.repository.submit_for_review(episode, "private://final.mp4")
        updated, review = self.repository.decide(
            awaiting,
            "owner-subject",
            ReviewDecision.REJECT,
            "Replace the opening visual.",
        )
        self.assertEqual(updated.status, EpisodeStatus.REJECTED)
        self.assertEqual(self.repository.claim_next().id, "episode-1")
        self.assertEqual(self.repository.reviews_for("episode-1"), (review,))

    def test_approval_keeps_private_video_reference(self) -> None:
        episode = Episode("episode-1", self.topic, EpisodeStatus.PROCESSING, 1)
        self.repository.save(episode)
        awaiting = self.repository.submit_for_review(episode, "private://final.mp4")
        approved, _ = self.repository.decide(
            awaiting, "owner-subject", ReviewDecision.APPROVE
        )
        persisted = self.repository.get("episode-1")
        self.assertEqual(approved.status, EpisodeStatus.APPROVED)
        self.assertEqual(persisted.final_video_uri, "private://final.mp4")
        with self.assertRaises(LookupError):
            self.repository.claim_next()

    def test_stale_review_decision_is_not_recorded(self) -> None:
        episode = Episode("episode-1", self.topic, EpisodeStatus.PROCESSING, 1)
        self.repository.save(episode)
        awaiting = self.repository.submit_for_review(episode, "private://final.mp4")
        self.repository.decide(awaiting, "owner-subject", ReviewDecision.APPROVE)

        with self.assertRaisesRegex(ValueError, "changed"):
            self.repository.decide(
                awaiting,
                "owner-subject",
                ReviewDecision.REJECT,
                "This decision is stale.",
            )
        self.assertEqual(len(self.repository.reviews_for("episode-1")), 1)
