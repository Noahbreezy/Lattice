"""Media validation checks for rendered review artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaIssue:
    code: str
    message: str


@dataclass(frozen=True)
class MediaReport:
    issues: tuple[MediaIssue, ...]
    metrics: dict[str, object] | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool = False

    @property
    def passed(self) -> bool:
        return not self.issues


def check_media(
    path: str | Path,
    expected_duration: int | None = None,
    tolerance_seconds: float = 1.0,
    maximum_duration: int | None = None,
) -> MediaReport:
    """Validate existence, stream presence, vertical dimensions, and duration."""

    media = Path(path)
    issues: list[MediaIssue] = []
    if not media.exists() or media.stat().st_size == 0:
        return MediaReport(
            (MediaIssue("missing-media", "Rendered media is missing or empty."),)
        )
    if shutil.which("ffprobe") is None:
        return MediaReport(
            (
                MediaIssue(
                    "ffprobe-unavailable", "FFprobe is required for media validation."
                ),
            )
        )
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(media),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return MediaReport((MediaIssue("invalid-container", completed.stderr.strip()),))
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return MediaReport(
            (MediaIssue("invalid-probe", "FFprobe returned invalid JSON."),)
        )
    streams = data.get("streams", [])
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    if video is None:
        issues.append(MediaIssue("missing-video", "The file has no video stream."))
    elif video.get("width") != 1080 or video.get("height") != 1920:
        issues.append(
            MediaIssue("wrong-format", "Expected a 1080x1920 vertical video.")
        )
    if audio is None:
        issues.append(MediaIssue("missing-audio", "The file has no audio stream."))
    duration = float(data.get("format", {}).get("duration", 0))
    if (
        expected_duration is not None
        and abs(duration - expected_duration) > tolerance_seconds
    ):
        issues.append(
            MediaIssue(
                "duration", f"Expected about {expected_duration}s, got {duration:.2f}s."
            )
        )
    if maximum_duration is not None and duration >= maximum_duration + 1:
        issues.append(
            MediaIssue(
                "maximum-duration",
                f"Video must stay under {maximum_duration + 1}s; got {duration:.2f}s.",
            )
        )
    metrics = (
        measure_animation(media)
        if not issues
        or not any(issue.code in {"missing-video", "wrong-format"} for issue in issues)
        else None
    )
    return MediaReport(
        tuple(issues),
        metrics,
        video.get("width") if video else None,
        video.get("height") if video else None,
        audio is not None,
    )


def measure_animation(path: str | Path, *, max_samples: int = 32) -> dict[str, object]:
    """Measure bounded frame differences using deterministic low-res samples.

    The metric is deliberately modest: at most ``max_samples`` 32x32 grayscale
    frames are read from FFmpeg, so evidence generation cannot grow with video
    duration or resolution.
    """

    if max_samples < 2:
        raise ValueError("max_samples must be at least 2")
    media = Path(path)
    if not media.is_file() or shutil.which("ffmpeg") is None:
        return {
            "method": "ffmpeg-frame-difference",
            "sample_count": 0,
            "mean_abs_diff": 0.0,
        }
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(media),
        "-vf",
        "fps=2,scale=32:32:flags=area,format=gray",
        "-frames:v",
        str(max_samples),
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    frame_size = 32 * 32
    frames = [
        completed.stdout[index : index + frame_size]
        for index in range(0, len(completed.stdout), frame_size)
        if len(completed.stdout[index : index + frame_size]) == frame_size
    ][:max_samples]
    differences = [
        sum(abs(left - right) for left, right in zip(frames[index - 1], frames[index]))
        / (255.0 * frame_size)
        for index in range(1, len(frames))
    ]
    return {
        "method": "ffmpeg-frame-difference",
        "sample_count": len(frames),
        "comparison_count": len(differences),
        "mean_abs_diff": round(sum(differences) / len(differences), 6)
        if differences
        else 0.0,
        "max_abs_diff": round(max(differences), 6) if differences else 0.0,
        "bounded": True,
    }


def media_fingerprint(path: str | Path) -> dict[str, object]:
    """Return stable identity data for a rendered media file."""

    media = Path(path)
    if not media.is_file():
        return {"path": str(media), "sha256": "", "bytes": 0}
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    return {"path": str(media), "sha256": digest, "bytes": media.stat().st_size}
