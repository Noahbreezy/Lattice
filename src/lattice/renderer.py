"""Local FFmpeg renderer for development and private single-machine use."""

from __future__ import annotations

import math
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from .contracts import AssetReference, PublishedVideo, RenderJob, RenderJobStatus
from .pipeline import publish_video
from .tts import (
    Narration,
    TtsProvider,
    WindowsSpeechTts,
    reconcile_storyboard_timing,
    validate_narration,
)
from .visuals import IllustratedVisualProvider, VisualProvider


class FfmpegRenderer:
    """Render illustrated vertical scenes with optional local narration."""

    def __init__(
        self,
        output_dir: str | Path,
        ffmpeg: str = "ffmpeg",
        tts_provider: TtsProvider | None = None,
        visual_provider: VisualProvider | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg = ffmpeg
        # Narration is mandatory for the local MVP. Callers may inject a local
        # provider for tests or an installed offline engine.
        self.tts_provider = tts_provider or WindowsSpeechTts()
        self.visual_provider = visual_provider or IllustratedVisualProvider()
        self.last_job: RenderJob | None = None

    def render(self, job: RenderJob) -> PublishedVideo:
        if job.status == RenderJobStatus.QUEUED:
            job = job.transition_to(RenderJobStatus.RUNNING)
            job = job.transition_to(RenderJobStatus.SUCCEEDED)
        elif job.status != RenderJobStatus.SUCCEEDED:
            raise ValueError("Only queued or succeeded render jobs can be rendered.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / f"{job.job_id.replace(':', '_')}.mp4"
        subtitle_path = self.output_dir / f"{job.job_id.replace(':', '_')}.srt"
        duration = max(
            1, sum(scene.duration_seconds for scene in job.storyboard.scenes)
        )
        with tempfile.TemporaryDirectory() as directory:
            job = _materialize_assets(
                job,
                self.output_dir / "assets" / job.job_id.replace(":", "_"),
                self.visual_provider,
            )
            narration = self._narrate(job, Path(directory))
            if narration is not None:
                job = replace(
                    job,
                    storyboard=reconcile_storyboard_timing(job.storyboard, narration),
                )
                duration = max(
                    math.ceil(narration.duration_seconds),
                    sum(scene.duration_seconds for scene in job.storyboard.scenes),
                )
            subtitle_path.write_text(_srt(job), encoding="utf-8")
            command = _render_command(
                self.ffmpeg,
                job,
                output,
                duration,
                narration.audio_uri if narration else None,
            )
            try:
                completed = subprocess.run(
                    command, check=False, capture_output=True, text=True
                )
            except OSError as exc:
                raise RuntimeError(f"Could not start FFmpeg: {exc}") from exc
            if completed.returncode != 0:
                detail = completed.stderr.strip().splitlines()[-1:] or [
                    "unknown FFmpeg error"
                ]
                raise RuntimeError(f"FFmpeg render failed: {detail[0]}")
            self.last_job = job
        return publish_video(job, str(output))

    def _narrate(self, job: RenderJob, directory: Path) -> Narration | None:
        text = " ".join(scene.narration for scene in job.storyboard.scenes)
        return validate_narration(
            self.tts_provider.synthesize(text, directory / "narration.wav")
        )


def _render_command(
    ffmpeg: str,
    job: RenderJob,
    output: Path,
    duration: int,
    audio_uri: str | None,
) -> list[str]:
    supports_svg = _supports_svg(ffmpeg)
    inputs: list[str] = [ffmpeg, "-y"]
    labels: list[str] = []
    for index in range(len(job.storyboard.scenes)):
        asset = job.asset_manifest.assets[index]
        if supports_svg or not asset.uri.endswith(".txt"):
            inputs.extend(["-loop", "1", "-framerate", "30", "-i", asset.uri])
        else:
            inputs.extend(["-f", "lavfi", "-i", "color=c=0x172554:s=1080x1920:r=30"])
        label = f"[v{index}]"
        labels.append(label)
    if audio_uri:
        inputs.extend(["-i", audio_uri])
        audio_label = f"{len(job.storyboard.scenes)}:a"
    else:
        inputs.extend(
            ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        )
        audio_label = f"{len(job.storyboard.scenes)}:a"
    filters: list[str] = []
    for index in range(len(job.storyboard.scenes)):
        accent = "0xfbbf24" if index % 2 == 0 else "0x67e8f9"
        if supports_svg or not job.asset_manifest.assets[index].uri.endswith(".txt"):
            visual = f"[{index}:v]scale=1080:1920"
        else:
            textfile = _ffmpeg_path(job.asset_manifest.assets[index].uri)
            visual = (
                f"[{index}:v]drawbox=x=80:y=250:w=920:h=1450:"
                f"color=0x0f172a@0.72:t=fill,"
                f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':"
                f"textfile='{textfile}':fontcolor=white:fontsize=42:"
                f"x=125:y=330:line_spacing=18"
            )
        filters.append(
            visual + ",format=yuv420p,"
            f"trim=duration={job.storyboard.scenes[index].duration_seconds},"
            f"setpts=PTS-STARTPTS,drawbox=x=90:y={240 + index * 35}:w=900:h=8:"
            f"color={accent}:t=fill,drawbox=x=120:y=1450:w=840:h=260:"
            f"color=0x0f172a@0.55:t=fill[v{index}]"
        )
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")
    return inputs + [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-map",
        f"{audio_label}",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-af",
        "apad",
        "-c:a",
        "aac",
        str(output),
    ]


def _supports_svg(ffmpeg: str) -> bool:
    try:
        completed = subprocess.run(
            [ffmpeg, "-decoders"], capture_output=True, text=True, check=False
        )
    except OSError:
        return False
    return completed.returncode == 0 and " svg " in completed.stdout.lower()


def _ffmpeg_path(path: str) -> str:
    """Escape a Windows path for FFmpeg filter options."""

    return str(Path(path)).replace("\\", "/").replace(":", "\\:")


def _materialize_assets(
    job: RenderJob, directory: Path, provider: VisualProvider
) -> RenderJob:
    assets: list[AssetReference] = []
    for index, asset in enumerate(job.asset_manifest.assets):
        if Path(asset.uri).is_file() and asset.uri.endswith(".svg"):
            assets.append(asset)
            continue
        created = provider.create(job.storyboard.scenes[index], directory / "assets")
        assets.append(created)
    if not _supports_svg("ffmpeg"):
        fallback_assets: list[AssetReference] = []
        for index, asset in enumerate(assets):
            if not asset.uri.endswith(".svg"):
                fallback_assets.append(asset)
                continue
            scene = job.storyboard.scenes[index]
            fallback = directory / "assets" / f"{scene.scene_id}.txt"
            fallback.write_text(
                "HOW IT WORKS\n\n"
                f"{scene.script_section_heading}\n\n"
                f"CAUSE: {scene.narration}\n\n"
                "MECHANISM: Follow the narrated explanation.\n\n"
                "OUTCOME: Apply the idea to the example.",
                encoding="utf-8",
            )
            fallback_assets.append(
                replace(asset, asset_type="text-illustration", uri=str(fallback))
            )
        assets = fallback_assets
    return replace(
        job, asset_manifest=replace(job.asset_manifest, assets=tuple(assets))
    )


def _srt(job: RenderJob) -> str:
    lines: list[str] = []
    elapsed = 0
    for index, scene in enumerate(job.storyboard.scenes, start=1):
        start = _timestamp(elapsed)
        elapsed += scene.duration_seconds
        lines.append(f"{index}\n{start} --> {_timestamp(elapsed)}\n{scene.narration}\n")
    return "\n".join(lines)


def _timestamp(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},000"
