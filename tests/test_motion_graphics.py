"""A short real FFmpeg export verifies the local motion graphics path."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lattice.config import load_config
from lattice.contracts import (
    AssetManifest,
    AssetReference,
    SceneBeat,
    Storyboard,
    StoryboardScene,
)
from lattice.media_quality import check_media
from lattice.motion_graphics import MotionGraphicsRenderer
from lattice.pipeline import create_render_job
from lattice.runner import configured_renderer, validate_local_capabilities
from lattice.tts import KokoroTts, Narration, WordTiming


class _FixtureVoice:
    def synthesize(self, text: str, output_path: str | Path) -> Narration:
        path = Path(output_path)
        sample_rate = 24_000
        duration = 0.4
        samples = array(
            "h",
            (
                round(9000 * math.sin(2 * math.pi * 220 * index / sample_rate))
                for index in range(round(duration * sample_rate))
            ),
        )
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(samples.tobytes())
        return Narration(
            str(path), duration, (WordTiming(text, 0, duration),), "fixture"
        )


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
)
class MotionGraphicsTests(unittest.TestCase):
    def test_kokoro_adapter_reuses_local_model_and_voice(self) -> None:
        calls: list[tuple[str, float, str]] = []

        class FakeKokoro:
            def __init__(self, model: str, voices: str) -> None:
                self.model, self.voices = model, voices

            def create(
                self, text: str, *, voice: str, speed: float, lang: str
            ) -> tuple[list[float], int]:
                del text
                calls.append((voice, speed, lang))
                return [0.25] * 2400, 24_000

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, voices = root / "model.onnx", root / "voices.bin"
            model.touch()
            voices.touch()
            provider = KokoroTts(model, voices, voice="am_michael", speed=1.1)
            with patch(
                "lattice.tts.import_module",
                return_value=SimpleNamespace(Kokoro=FakeKokoro),
            ):
                first = provider.synthesize("First beat", root / "first.wav")
                second = provider.synthesize("Second beat", root / "second.wav")
            self.assertEqual(calls, [("am_michael", 1.1, "en-us")] * 2)
            self.assertEqual(first.provider, "kokoro-onnx")
            self.assertTrue(Path(second.audio_uri).is_file())

    def test_example_config_selects_local_graphics_mode(self) -> None:
        config = load_config(
            Path(__file__).parents[1]
            / "configs"
            / "knowledge-channel-motion-graphics.json"
        )
        validate_local_capabilities(config, offline=True)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsInstance(
                configured_renderer(config, Path(directory)), MotionGraphicsRenderer
            )

    def test_editable_plan_produces_timed_vertical_video(self) -> None:
        scene = StoryboardScene(
            "scene-1",
            "The idea",
            "One ticket closes. The problem remains.",
            "Show two diverging measures.",
            2,
            (
                SceneBeat(0, 1, "Raise the closed count.", "One ticket closes."),
                SceneBeat(1, 2, "Keep resolution flat.", "The problem remains."),
            ),
        )
        storyboard = Storyboard((scene,), maximum_duration_seconds=179)
        manifest = AssetManifest(
            (AssetReference("visual-1", "placeholder", "local://visual-1"),)
        )
        job = create_render_job(storyboard, manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "edit.json"
            plan.write_text(
                json.dumps(
                    {
                        "scenes": {
                            "scene-1": [
                                {
                                    "motif": "tickets",
                                    "title": "Tickets closed",
                                    "left_end": 8,
                                    "right_end": 0,
                                },
                                {
                                    "title": "Problems resolved",
                                    "left_end": 8,
                                    "right_end": 0,
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            renderer = MotionGraphicsRenderer(
                root, tts_provider=_FixtureVoice(), plan_path=plan, fps=8
            )
            video = renderer.render(job)
            report = check_media(
                video.uri,
                expected_duration=2,
                require_motion=True,
                require_audible=True,
                require_captions=True,
            )
            self.assertTrue(report.passed, report.issues)
            self.assertEqual((report.width, report.height), (720, 1280))
            self.assertTrue((root / "render_storyboard_v1.motion-plan.json").is_file())
            self.assertIn(
                "The problem remains.", (root / "render_storyboard_v1.srt").read_text()
            )

    def test_rejects_non_vertical_dimensions(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "9:16"),
        ):
            MotionGraphicsRenderer(
                directory, tts_provider=_FixtureVoice(), width=720, height=720
            )


if __name__ == "__main__":
    unittest.main()
