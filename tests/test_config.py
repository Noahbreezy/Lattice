import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from lattice.config import ConfigError, ProjectConfig, load_config
from lattice.renderer import FfmpegRenderer
from lattice.runner import configured_renderer, validate_local_capabilities


class ProjectConfigTests(unittest.TestCase):
    def test_loads_example_configuration(self) -> None:
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        self.assertEqual(config.channel_name, "A New Thing")
        self.assertEqual(config.max_video_length_seconds, 179)
        self.assertIn("The idea", config.required_sections)
        self.assertEqual(config.retention.max_server_videos, 5)
        validate_local_capabilities(config, offline=False)

    def test_runner_rejects_unavailable_required_provider_and_workflow(self) -> None:
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        tools = tuple(
            {**tool, "required": True} if tool["name"] == "video generator" else tool
            for tool in config.ai_tools
        )
        with self.assertRaisesRegex(ValueError, "video generator"):
            validate_local_capabilities(replace(config, ai_tools=tools), offline=False)
        with self.assertRaisesRegex(ValueError, "workflow"):
            validate_local_capabilities(
                replace(config, workflow=("render and caption video",)), offline=False
            )

    def test_configured_visual_adapter_reaches_renderer(self) -> None:
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        tools = tuple(
            {**tool, "provider": "custom", "required": True}
            if tool["name"] == "video generator"
            else tool
            for tool in config.ai_tools
        )
        custom = replace(config, ai_tools=tools)
        visual = object()
        def create_visual(*_args: object) -> object:
            del _args
            return visual

        def factory(capability: str, name: str):
            if (capability, name) == ("visual", "custom"):
                return create_visual
            return None
        with patch(
            "lattice.runner.provider_factory",
            side_effect=factory,
        ):
            validate_local_capabilities(custom, offline=False)
            renderer = configured_renderer(custom, Path("var/test"))
            assert isinstance(renderer, FfmpegRenderer)
            self.assertIs(
                renderer.visual_provider, visual
            )

    def test_rejects_invalid_video_length(self) -> None:
        with self.assertRaisesRegex(ConfigError, "max_video_length_seconds"):
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
                        "max_video_length_seconds": 180,
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
        raw: dict[str, object] = {
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
                "max_video_length_seconds": 179,
                "traits": ["x"],
                "workflow": ["x"],
                "ai_tools": [],
                "retention": {"max_cloud_videos": -1},
            },
        }
        with self.assertRaisesRegex(ConfigError, "max_cloud_videos"):
            ProjectConfig.from_mapping(raw)

    def test_partial_retention_keeps_default_limits(self) -> None:
        raw: dict[str, object] = {
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
                "max_video_length_seconds": 179,
                "traits": ["x"],
                "workflow": ["x"],
                "ai_tools": [],
                "retention": {"max_server_videos": 1},
            },
        }
        retention = ProjectConfig.from_mapping(raw).retention
        self.assertEqual(retention.max_server_videos, 1)
        self.assertEqual(retention.max_cloud_videos, 100)
        self.assertEqual(retention.max_approved_videos, 100)


if __name__ == "__main__":
    unittest.main()
