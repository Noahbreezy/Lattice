import json
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
            )
            self.assertEqual(result.status, EpisodeStatus.AWAITING_REVIEW)
            self.assertTrue(Path(result.final_video_uri).is_file())
            self.assertTrue(
                (Path(result.final_video_uri).with_suffix(".srt")).is_file()
            )
            lesson = json.loads(Path(result.lesson_uri).read_text(encoding="utf-8"))
            script = json.loads(Path(result.script_uri).read_text(encoding="utf-8"))
            self.assertEqual(lesson["kind"], "lesson")
            self.assertEqual(lesson["episode_id"], result.id)
            self.assertTrue(lesson["sections"])
            self.assertEqual(script["kind"], "script")
            self.assertIn("production_script", script)
            persisted = repository.get(result.id)
            self.assertEqual(persisted.lesson_uri, result.lesson_uri)
            self.assertEqual(persisted.script_uri, result.script_uri)
            repository.close()


if __name__ == "__main__":
    unittest.main()
