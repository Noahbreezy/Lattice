import tempfile
import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Episode, EpisodeStatus, Topic
from lattice.history import LessonHistory
from lattice.persistence import EpisodeRepository
from lattice.pipeline import build_production_bundle
from lattice.production import render_episode_for_review
from lattice.renderer import FfmpegRenderer
from lattice.storage import LocalObjectStorage


class ProductionTests(unittest.TestCase):
    def test_quality_gated_render_persists_artifacts_and_submits(self) -> None:
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            history = LessonHistory(Path(directory) / "history.json")
            bundle = build_production_bundle(config, history, offline=True)
            repository = EpisodeRepository()
            episode = Episode(
                "episode-1",
                Topic(bundle.draft.topic.title, bundle.draft.topic.subject_area),
                EpisodeStatus.PROCESSING,
                1,
            )
            storage = LocalObjectStorage(Path(directory) / "objects")
            result = render_episode_for_review(
                bundle,
                episode,
                FfmpegRenderer(Path(directory) / "render"),
                repository,
                storage,
                expected_duration=sum(
                    scene.duration_seconds for scene in bundle.storyboard.scenes
                ),
            )
            self.assertEqual(result.status, EpisodeStatus.AWAITING_REVIEW)
            self.assertTrue(Path(result.final_video_uri).is_file())
            self.assertTrue(
                (Path(result.final_video_uri).with_suffix(".srt")).is_file()
            )
            repository.close()


if __name__ == "__main__":
    unittest.main()
