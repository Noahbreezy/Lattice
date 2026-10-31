import unittest

from lattice.config import ConfigError, RetentionSettings
from lattice.contracts import EpisodeStatus
from lattice.retention import (
    StorageLocation,
    StoredVideo,
    plan_retention,
)


class RetentionTests(unittest.TestCase):
    def test_oldest_videos_are_selected_for_each_limit(self) -> None:
        videos = tuple(
            StoredVideo(
                id=f"video-{index}",
                status=EpisodeStatus.APPROVED,
                location=StorageLocation.CLOUD,
                created_at=f"2026-01-0{index}T00:00:00+00:00",
            )
            for index in range(1, 4)
        )
        actions = plan_retention(
            videos,
            RetentionSettings(
                max_cloud_videos=2,
                max_server_videos=None,
                max_approved_videos=2,
                max_rejected_videos=None,
                max_awaiting_review_videos=None,
            ),
        )
        self.assertEqual([action.video_id for action in actions], ["video-1"])

    def test_combined_limits_do_not_duplicate_deletion_actions(self) -> None:
        videos = (
            StoredVideo(
                "old",
                EpisodeStatus.REJECTED,
                StorageLocation.SERVER,
                "2026-01-01",
            ),
            StoredVideo(
                "new",
                EpisodeStatus.REJECTED,
                StorageLocation.SERVER,
                "2026-01-02",
            ),
        )
        actions = plan_retention(
            videos,
            RetentionSettings(
                max_cloud_videos=None,
                max_server_videos=1,
                max_approved_videos=None,
                max_rejected_videos=1,
                max_awaiting_review_videos=None,
            ),
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].video_id, "old")

    def test_invalid_retention_limit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "max_cloud_videos"):
            RetentionSettings(max_cloud_videos=-1)
