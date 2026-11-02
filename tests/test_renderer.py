import shutil
import tempfile
import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.pipeline import (
    build_asset_manifest,
    build_research_packet,
    build_script,
    build_storyboard,
    create_render_job,
)
from lattice.renderer import FfmpegRenderer
from lattice.contracts import RenderJobStatus, Topic
from lattice.media_quality import check_media


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for local renderer tests.")
class RendererTests(unittest.TestCase):
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
            video = FfmpegRenderer(directory).render(job)
            self.assertTrue(Path(video.uri).exists())
            self.assertGreater(Path(video.uri).stat().st_size, 0)
            self.assertEqual(len(tuple(Path(directory).glob("*.srt"))), 1)
            report = check_media(video.uri, expected_duration=config.video_length_seconds)
            self.assertTrue(report.passed, report.issues)
