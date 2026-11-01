"""Local FFmpeg renderer for development and private single-machine use."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .contracts import PublishedVideo, RenderJob, RenderJobStatus
from .pipeline import publish_video


class FfmpegRenderer:
    """Render a storyboard into a silent, vertically formatted MP4.

    The renderer deliberately uses generated color slates until a visual asset
    provider is configured. It still exercises the real media container,
    encoding, duration, and private-artifact lifecycle.
    """

    def __init__(self, output_dir: str | Path, ffmpeg: str = "ffmpeg") -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg = ffmpeg

    def render(self, job: RenderJob) -> PublishedVideo:
        if job.status == RenderJobStatus.QUEUED:
            job = job.transition_to(RenderJobStatus.RUNNING)
            job = job.transition_to(RenderJobStatus.SUCCEEDED)
        elif job.status != RenderJobStatus.SUCCEEDED:
            raise ValueError("Only queued or succeeded render jobs can be rendered.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / f"{job.job_id.replace(':', '_')}.mp4"
        subtitle_path = self.output_dir / f"{job.job_id.replace(':', '_')}.srt"
        subtitle_path.write_text(_srt(job), encoding="utf-8")
        duration = max(1, sum(scene.duration_seconds for scene in job.storyboard.scenes))
        command = [
            self.ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x172554:s=1080x1920:r=30:d={duration}",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start FFmpeg: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()[-1:] or ["unknown FFmpeg error"]
            raise RuntimeError(f"FFmpeg render failed: {detail[0]}")
        return publish_video(job, str(output))


def _srt(job: RenderJob) -> str:
    lines: list[str] = []
    elapsed = 0
    for index, scene in enumerate(job.storyboard.scenes, start=1):
        start = _timestamp(elapsed)
        elapsed += scene.duration_seconds
        lines.append(
            f"{index}\n{start} --> {_timestamp(elapsed)}\n{scene.narration}\n"
        )
    return "\n".join(lines)


def _timestamp(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},000"
