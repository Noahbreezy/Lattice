"""Local FFmpeg renderer for development and private single-machine use."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from .tts import Narration, TtsProvider

from .contracts import PublishedVideo, RenderJob, RenderJobStatus
from .pipeline import publish_video


class FfmpegRenderer:
    """Render illustrated vertical scenes with optional local narration."""

    def __init__(
        self,
        output_dir: str | Path,
        ffmpeg: str = "ffmpeg",
        tts_provider: TtsProvider | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg = ffmpeg
        self.tts_provider = tts_provider

    def render(self, job: RenderJob) -> PublishedVideo:
        if job.status == RenderJobStatus.QUEUED:
            job = job.transition_to(RenderJobStatus.RUNNING)
            job = job.transition_to(RenderJobStatus.SUCCEEDED)
        elif job.status != RenderJobStatus.SUCCEEDED:
            raise ValueError("Only queued or succeeded render jobs can be rendered.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / f"{job.job_id.replace(':', '_')}.mp4"
        subtitle_path = self.output_dir / f"{job.job_id.replace(':', '_')}.srt"
        duration = max(1, sum(scene.duration_seconds for scene in job.storyboard.scenes))
        with tempfile.TemporaryDirectory() as directory:
            narration = self._narrate(job, Path(directory))
            subtitle_path.write_text(_srt(job, narration), encoding="utf-8")
            command = _render_command(
                self.ffmpeg, job, output, duration, narration.audio_uri if narration else None
            )
            try:
                completed = subprocess.run(
                    command, check=False, capture_output=True, text=True
                )
            except OSError as exc:
                raise RuntimeError(f"Could not start FFmpeg: {exc}") from exc
            if completed.returncode != 0:
                detail = completed.stderr.strip().splitlines()[-1:] or ["unknown FFmpeg error"]
                raise RuntimeError(f"FFmpeg render failed: {detail[0]}")
        return publish_video(job, str(output))

    def _narrate(self, job: RenderJob, directory: Path) -> Narration | None:
        if self.tts_provider is None:
            return None
        text = " ".join(scene.narration for scene in job.storyboard.scenes)
        return self.tts_provider.synthesize(text, directory / "narration.wav")

def _render_command(
    ffmpeg: str,
    job: RenderJob,
    output: Path,
    duration: int,
    audio_uri: str | None,
) -> list[str]:
    colors = ("0x172554", "0x1e3a8a", "0x164e63", "0x365314", "0x713f12")
    inputs: list[str] = [ffmpeg, "-y"]
    labels: list[str] = []
    for index, scene in enumerate(job.storyboard.scenes):
        inputs.extend([
            "-f", "lavfi", "-i",
            f"color=c={colors[index % len(colors)]}:s=1080x1920:r=30:d={scene.duration_seconds}",
        ])
        label = f"[v{index}]"
        labels.append(label)
    if audio_uri:
        inputs.extend(["-i", audio_uri])
        audio_label = f"{len(job.storyboard.scenes)}:a"
    else:
        inputs.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
        audio_label = f"{len(job.storyboard.scenes)}:a"
    filters = []
    for index, _scene in enumerate(job.storyboard.scenes):
        accent = "0xfbbf24" if index % 2 == 0 else "0x67e8f9"
        filters.append(
            f"[{index}:v]drawbox=x=90:y={240 + index * 35}:w=900:h=8:"
            f"color={accent}:t=fill,drawbox=x=120:y=1450:w=840:h=260:"
            f"color=0x0f172a@0.55:t=fill[v{index}]"
        )
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")
    return inputs + [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", f"{audio_label}",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-af", "apad", "-c:a", "aac", str(output),
    ]


def _srt(job: RenderJob, narration: Narration | None = None) -> str:
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
