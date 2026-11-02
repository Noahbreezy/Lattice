"""Media validation checks for rendered review artifacts."""

from __future__ import annotations

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

    @property
    def passed(self) -> bool:
        return not self.issues


def check_media(
    path: str | Path,
    expected_duration: int | None = None,
    tolerance_seconds: float = 1.0,
) -> MediaReport:
    """Validate existence, stream presence, vertical dimensions, and duration."""

    media = Path(path)
    issues: list[MediaIssue] = []
    if not media.exists() or media.stat().st_size == 0:
        return MediaReport((MediaIssue("missing-media", "Rendered media is missing or empty."),))
    if shutil.which("ffprobe") is None:
        return MediaReport((MediaIssue("ffprobe-unavailable", "FFprobe is required for media validation."),))
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return MediaReport((MediaIssue("invalid-container", completed.stderr.strip()),))
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return MediaReport((MediaIssue("invalid-probe", "FFprobe returned invalid JSON."),))
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        issues.append(MediaIssue("missing-video", "The file has no video stream."))
    elif video.get("width") != 1080 or video.get("height") != 1920:
        issues.append(MediaIssue("wrong-format", "Expected a 1080x1920 vertical video."))
    if audio is None:
        issues.append(MediaIssue("missing-audio", "The file has no audio stream."))
    duration = float(data.get("format", {}).get("duration", 0))
    if expected_duration is not None and abs(duration - expected_duration) > tolerance_seconds:
        issues.append(MediaIssue("duration", f"Expected about {expected_duration}s, got {duration:.2f}s."))
    return MediaReport(tuple(issues))
