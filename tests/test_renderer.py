import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Topic
from lattice.media_quality import check_media, measure_animation
from lattice.pipeline import (
    build_asset_manifest,
    build_research_packet,
    build_script,
    build_storyboard,
    create_render_job,
)
from lattice.renderer import FfmpegRenderer
from lattice.tts import Narration, _proportional_timings


class FixtureTts:
    def synthesize(self, text: str, output_path: str | Path) -> Narration:
        path = Path(output_path)
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x01\x00" * 8000 * 30)
        duration = 30.0
        words = text.split()
        return Narration(
            str(path), duration, _proportional_timings(words, duration), "fixture"
        )


@unittest.skipUnless(
    shutil.which("ffmpeg"), "FFmpeg is required for local renderer tests."
)
class RendererTests(unittest.TestCase):
    def test_animation_metric_is_bounded_and_distinguishes_motion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            static = Path(directory) / "static.mp4"
            moving = Path(directory) / "moving.mp4"
            for output, source in (
                (static, "color=c=black:s=64x64:r=2"),
                (moving, "testsrc=s=64x64:r=2"),
            ):
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        source,
                        "-t",
                        "2",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                )
            static_metric = measure_animation(static)
            moving_metric = measure_animation(moving)
            self.assertLessEqual(static_metric["sample_count"], 32)
            self.assertEqual(static_metric["mean_abs_diff"], 0.0)
            self.assertGreater(moving_metric["mean_abs_diff"], 0.0)
            report = check_media(static, require_motion=True)
            self.assertIn("frozen-video", {issue.code for issue in report.issues})
            self.assertIn(
                "missing-captions",
                {
                    issue.code
                    for issue in check_media(moving, require_captions=True).issues
                },
            )

    def test_final_media_gate_rejects_silent_muxed_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "silent.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=s=64x64:r=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=8000:cl=mono",
                    "-t",
                    "2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(output),
                ],
                check=True,
                capture_output=True,
            )
            report = check_media(output, require_audible=True)
            self.assertIn("inaudible-audio", {issue.code for issue in report.issues})

    def test_renderer_creates_private_mp4(self) -> None:
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        research = build_research_packet(Topic("A topic", "systems"))
        script = build_script(config, research)
        storyboard = build_storyboard(config, script)
        manifest = build_asset_manifest(storyboard)
        job = create_render_job(storyboard, manifest)
        with tempfile.TemporaryDirectory() as directory:
            renderer = FfmpegRenderer(directory, tts_provider=FixtureTts())
            video = renderer.render(job)
            self.assertTrue(Path(video.uri).exists())
            self.assertGreater(Path(video.uri).stat().st_size, 0)
            self.assertEqual(len(tuple(Path(directory).glob("*.srt"))), 1)
            self.assertIsNotNone(renderer.last_job)
            expected_duration = sum(
                scene.duration_seconds for scene in renderer.last_job.storyboard.scenes
            )
            report = check_media(video.uri, expected_duration=expected_duration)
            self.assertTrue(report.passed, report.issues)
