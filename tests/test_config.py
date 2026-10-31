import json
import tempfile
import unittest
from pathlib import Path

from lattice.config import ConfigError, ProjectConfig, load_config


class ProjectConfigTests(unittest.TestCase):
    def test_loads_example_configuration(self) -> None:
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        self.assertEqual(config.channel_name, "A New Thing")
        self.assertEqual(config.video_length_seconds, 75)
        self.assertIn("The idea", config.required_sections)
        self.assertEqual(config.retention.max_server_videos, 5)

    def test_rejects_invalid_video_length(self) -> None:
        with self.assertRaisesRegex(ConfigError, "video_length_seconds"):
            ProjectConfig.from_mapping(
                {
                    "project": {"name": "x", "description": "x"},
                    "content": {
                        "channel_name": "x",
                        "format": "x",
                        "prompt": "x",
                        "required_sections": ["x"],
                    },
                    "production": {
                        "video_length_seconds": 0,
                        "traits": ["x"],
                        "workflow": ["x"],
                        "ai_tools": [],
                    },
                }
            )

    def test_reports_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Invalid JSON"):
                load_config(path)

    def test_rejects_negative_retention_limit(self) -> None:
        raw = {
            "project": {"name": "x", "description": "x"},
            "content": {
                "channel_name": "x",
                "format": "x",
                "prompt": "x",
                "required_sections": ["x"],
                "subject_areas": ["x"],
                "learning_rules": ["x"],
            },
            "production": {
                "video_length_seconds": 60,
                "traits": ["x"],
                "workflow": ["x"],
                "ai_tools": [],
                "retention": {"max_cloud_videos": -1},
            },
        }
        with self.assertRaisesRegex(ConfigError, "max_cloud_videos"):
            ProjectConfig.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
