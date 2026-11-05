import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lattice.cli import run_local_main
from lattice.contracts import EpisodeStatus
from lattice.persistence import EpisodeRepository


class LocalCliTests(unittest.TestCase):
    def test_local_run_writes_artifacts_and_persists_review(self) -> None:
        root = Path(__file__).parents[1]
        config = root / "configs" / "knowledge-channel.json"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            arguments = [
                "lattice-run-local",
                str(config),
                "--database",
                str(path / "review.sqlite"),
                "--output",
                str(path / "artifacts"),
                "--history",
                str(path / "history.json"),
            ]
            with patch.object(sys, "argv", arguments):
                self.assertEqual(run_local_main(), 0)
            repository = EpisodeRepository(path / "review.sqlite")
            episodes = repository.list_episodes()
            self.assertEqual(len(episodes), 1)
            self.assertEqual(episodes[0].status, EpisodeStatus.AWAITING_REVIEW)
            self.assertTrue(Path(episodes[0].final_video_uri).is_file())
            self.assertTrue(
                Path(episodes[0].final_video_uri)
                .with_name(Path(episodes[0].final_video_uri).stem + ".manifest.json")
                .is_file()
            )
            repository.close()

    def test_local_run_reports_invalid_config(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                sys,
                "argv",
                ["lattice-run-local", str(Path(directory) / "missing.json")],
            ),
        ):
            self.assertEqual(run_local_main(), 1)


if __name__ == "__main__":
    unittest.main()
