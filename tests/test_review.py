import unittest

from lattice.contracts import Episode, EpisodeStatus, ReviewDecision, Topic
from lattice.review import ReviewQueue


class ReviewQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = ReviewQueue()
        self.topic = Topic("A useful concept", "systems")

    def test_rejected_episode_is_requeued_before_unprocessed_work(self) -> None:
        untouched = Episode("untouched", self.topic, EpisodeStatus.QUEUED, 1)
        rejected = Episode(
            "rejected", self.topic, EpisodeStatus.AWAITING_REVIEW, 1, "s3://final/rejected.mp4"
        )
        self.queue.enqueue(untouched)
        updated, review = self.queue.decide(
            rejected, "owner", ReviewDecision.REJECT, "The opening needs a clearer example."
        )
        self.assertEqual(updated.status, EpisodeStatus.REJECTED)
        self.assertEqual(review.feedback, "The opening needs a clearer example.")
        self.assertEqual(self.queue.next().episode.id, "rejected")
        self.assertEqual(self.queue.next().episode.id, "untouched")

    def test_approval_preserves_video_for_later_upload(self) -> None:
        episode = Episode(
            "ready", self.topic, EpisodeStatus.AWAITING_REVIEW, 1, "s3://final/ready.mp4"
        )
        updated, _ = self.queue.decide(episode, "owner", ReviewDecision.APPROVE)
        self.assertEqual(updated.status, EpisodeStatus.APPROVED)
        self.assertEqual(updated.final_video_uri, "s3://final/ready.mp4")

    def test_rejection_requires_feedback(self) -> None:
        episode = Episode("needs-feedback", self.topic, EpisodeStatus.AWAITING_REVIEW, 1, "s3://x")
        with self.assertRaisesRegex(ValueError, "feedback"):
            self.queue.decide(episode, "owner", ReviewDecision.REJECT)

    def test_only_reviewable_episode_can_be_decided(self) -> None:
        episode = Episode("queued", self.topic, EpisodeStatus.QUEUED, 1)
        with self.assertRaisesRegex(ValueError, "awaiting review"):
            self.queue.decide(episode, "owner", ReviewDecision.APPROVE)
