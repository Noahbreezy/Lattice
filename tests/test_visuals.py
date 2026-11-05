import tempfile
import unittest
from pathlib import Path

from lattice.contracts import StoryboardScene
from lattice.visuals import IllustratedVisualProvider, validate_svg


class VisualTests(unittest.TestCase):
    def test_illustrated_provider_emits_valid_readable_svg(self) -> None:
        scene = StoryboardScene(
            "scene-1", "The idea", "Explain the idea.", "Show it.", 5
        )
        with tempfile.TemporaryDirectory() as directory:
            asset = IllustratedVisualProvider().create(scene, directory)
            validate_svg(asset.uri)
            self.assertEqual(Path(asset.uri).suffix, ".svg")
            svg = Path(asset.uri).read_text(encoding="utf-8")
            self.assertIn("CAUSE", svg)
            self.assertIn("MECHANISM", svg)
            self.assertIn("OUTCOME", svg)
            self.assertIn("marker-end", svg)

    def test_validator_rejects_executable_svg_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.svg"
            path.write_text(
                '<svg width="1080" height="1920"><script>alert(1)</script>'
                "<text>Readable</text></svg>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "executable"):
                validate_svg(path)
