"""Frame-accurate, editable motion graphics rendered locally with Pillow and FFmpeg."""

from __future__ import annotations

import bisect
import json
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from .contracts import PublishedVideo, RenderJob, RenderJobStatus, SceneBeat
from .pipeline import publish_video
from .tts import TtsProvider, validate_narration

_SAMPLE_RATE = 24_000


@dataclass(frozen=True)
class _TimedBeat:
    scene_id: str
    heading: str
    beat: SceneBeat
    start: int
    duration: int
    graphic: dict[str, object]


def _default_graphic(heading: str, beat: SceneBeat) -> dict[str, object]:
    return {
        "motif": "metrics",
        "title": heading,
        "note": beat.visual.split(". ", 1)[0].strip().rstrip("."),
        "left_label": "What is measured",
        "right_label": "What matters",
        "left_start": 0,
        "left_end": 8,
        "right_start": 0,
        "right_end": 4,
    }


def _prepare_plan(job: RenderJob, source: str | Path | None) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if source is not None:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"Motion plan not found: {path}")
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
        if not isinstance(raw, dict):
            raise ValueError("Motion plan must be a JSON object.")
        overrides = cast(dict[str, object], raw)
    scene_overrides = overrides.get("scenes", {})
    if not isinstance(scene_overrides, dict):
        raise TypeError("Motion plan scenes must be an object keyed by scene ID.")
    scene_overrides = cast(dict[str, object], scene_overrides)
    scenes: dict[str, list[dict[str, object]]] = {}
    for scene in job.storyboard.scenes:
        beats = scene.timing_sync or (
            SceneBeat(
                0, scene.duration_seconds, scene.visual_direction, scene.narration
            ),
        )
        custom = scene_overrides.get(scene.scene_id)
        if custom is None:
            custom_items: list[object] = []
        elif isinstance(custom, list):
            custom_items = cast(list[object], custom)
        else:
            raise ValueError(f"Invalid motion plan beats for {scene.scene_id}.")
        if len(custom_items) > len(beats):
            raise ValueError(f"Invalid motion plan beats for {scene.scene_id}.")
        graphics: list[dict[str, object]] = []
        for index, beat in enumerate(beats):
            item: object = custom_items[index] if index < len(custom_items) else {}
            if not isinstance(item, dict):
                raise TypeError("Each motion plan beat must be an object.")
            graphic: dict[str, object] = {
                **_default_graphic(scene.script_section_heading, beat),
                **cast(dict[str, object], item),
            }
            for key in ("title", "note", "left_label", "right_label"):
                if not isinstance(graphic.get(key), str):
                    raise TypeError(f"Motion plan {scene.scene_id} {key} must be text.")
            if graphic.get("motif") not in {"metrics", "tickets"}:
                raise ValueError("Motion plan motif must be metrics or tickets.")
            for key in ("left_start", "left_end", "right_start", "right_end"):
                value = graphic.get(key)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                ):
                    raise ValueError(
                        f"Motion plan {scene.scene_id} {key} must be non-negative."
                    )
            graphics.append(graphic)
        scenes[scene.scene_id] = graphics
    unknown = set(scene_overrides) - set(scenes)
    if unknown:
        raise ValueError(f"Unknown motion plan scenes: {', '.join(sorted(unknown))}")
    return {"version": 1, "scenes": scenes}


def _timed_beats(job: RenderJob, plan: dict[str, object]) -> list[_TimedBeat]:
    scenes = cast(dict[str, list[dict[str, object]]], plan["scenes"])
    result: list[_TimedBeat] = []
    scene_start = 0
    for scene in job.storyboard.scenes:
        beats = scene.timing_sync or (
            SceneBeat(
                0, scene.duration_seconds, scene.visual_direction, scene.narration
            ),
        )
        graphics = scenes[scene.scene_id]
        for index, beat in enumerate(beats):
            result.append(
                _TimedBeat(
                    scene.scene_id,
                    scene.script_section_heading,
                    beat,
                    scene_start + beat.start_seconds,
                    beat.end_seconds - beat.start_seconds,
                    graphics[index],
                )
            )
        scene_start += scene.duration_seconds
    return result


def _audio_track(
    beats: list[_TimedBeat], provider: TtsProvider, directory: Path, ffmpeg: str
) -> Path:
    output = directory / "narration.wav"
    with wave.open(str(output), "wb") as joined:
        joined.setnchannels(1)
        joined.setsampwidth(2)
        joined.setframerate(_SAMPLE_RATE)
        for index, beat in enumerate(beats):
            raw = directory / f"beat-{index:03d}.wav"
            narration = validate_narration(
                provider.synthesize(beat.beat.narration_excerpt, raw)
            )
            if narration.duration_seconds > beat.duration * 1.25:
                raise ValueError(
                    f"Narration for {beat.scene_id} beat {index + 1} exceeds its slot "
                    "by more than 25%; revise the beat or its timing."
                )
            tempo = max(
                1.0, narration.duration_seconds / max(0.1, beat.duration - 0.08)
            )
            normalized = directory / f"normalized-{index:03d}.wav"
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw),
                "-af",
                f"atempo={tempo:.5f}",
                "-ar",
                str(_SAMPLE_RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(normalized),
            ]
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            if completed.returncode:
                raise RuntimeError(
                    f"FFmpeg could not normalize beat audio: {completed.stderr.strip()}"
                )
            with wave.open(str(normalized), "rb") as clip:
                frames = clip.readframes(clip.getnframes())
            target_bytes = beat.duration * _SAMPLE_RATE * 2
            joined.writeframes(frames[:target_bytes].ljust(target_bytes, b"\0"))
    return output


def _captions(beats: list[_TimedBeat]) -> list[tuple[float, float, str]]:
    captions: list[tuple[float, float, str]] = []
    for beat in beats:
        words = beat.beat.narration_excerpt.split()
        phrases = [
            " ".join(words[index : index + 6]) for index in range(0, len(words), 6)
        ]
        for index, phrase in enumerate(phrases):
            start = beat.start + beat.duration * index / len(phrases)
            end = beat.start + beat.duration * (index + 1) / len(phrases)
            captions.append((start, end, phrase))
    return captions


def _srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, fraction = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{fraction:03d}"


def _write_srt(path: Path, captions: list[tuple[float, float, str]]) -> None:
    path.write_text(
        "\n".join(
            f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n"
            for index, (start, end, text) in enumerate(captions, 1)
        ),
        encoding="utf-8",
    )


@lru_cache(maxsize=16)
def _font(size: int):
    from PIL import ImageFont

    for name in ("C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: Any, value: str, font: Any, width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in value.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:max_lines]


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError("Motion plan metric values must be numbers.")
    return float(value)


def _frame(
    beat: _TimedBeat,
    progress: float,
    caption: str,
    width: int,
    height: int,
    scene_number: int,
    scene_count: int,
) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "#0b1733")
    draw = ImageDraw.Draw(image)
    scale = width / 720

    def s(value: int) -> int:
        return round(value * scale)

    title_font = _font(s(50))
    label_font = _font(s(29))
    number_font = _font(s(92))
    caption_font = _font(s(36))
    graphic = beat.graphic
    left = int(s(50))
    right = width - left
    draw.text(
        (left, s(65)),
        f"SCENE {scene_number:02d} / {scene_count:02d}",
        font=label_font,
        fill="#67e8f9",
    )
    for line_index, line in enumerate(
        _wrap(draw, str(graphic["title"]), title_font, width - 2 * left, 3)
    ):
        draw.text((left, s(130 + line_index * 62)), line, font=title_font, fill="white")
    draw.rounded_rectangle((left, s(350), right, s(855)), radius=s(28), fill="#14264c")
    eased = progress * progress * (3 - 2 * progress)
    if graphic["motif"] == "tickets":
        closed = (
            _number(graphic["left_start"])
            + (_number(graphic["left_end"]) - _number(graphic["left_start"])) * eased
        )
        resolved = (
            _number(graphic["right_start"])
            + (_number(graphic["right_end"]) - _number(graphic["right_start"])) * eased
        )
        draw.text(
            (left + s(30), s(380)),
            f"{graphic['left_label']}: {round(closed)}",
            font=label_font,
            fill="#fbbf24",
        )
        for index in range(3):
            y = s(450 + index * 105)
            draw.rounded_rectangle(
                (left + s(30), y, left + s(325), y + s(76)),
                radius=s(14),
                fill="#243c66",
            )
            draw.text(
                (left + s(48), y + s(21)),
                f"TICKET {index + 1}",
                font=label_font,
                fill="white",
            )
            state = "CLOSED" if progress >= (index + 1) / 4 else "OPEN"
            draw.text(
                (left + s(190), y + s(21)),
                state,
                font=label_font,
                fill="#fbbf24" if state == "CLOSED" else "#b8c9e5",
            )
        customer_x = right - s(105)
        draw.ellipse(
            (customer_x - s(33), s(480), customer_x + s(33), s(546)),
            fill="#67e8f9",
        )
        draw.rounded_rectangle(
            (customer_x - s(45), s(550), customer_x + s(45), s(680)),
            radius=s(20),
            fill="#67e8f9",
        )
        outcome = "RESOLVED" if resolved >= 1 else "STILL OPEN"
        draw.text((right - s(205), s(725)), outcome, font=label_font, fill="#67e8f9")
    else:
        for index, (prefix, color) in enumerate(
            (("left", "#fbbf24"), ("right", "#67e8f9"))
        ):
            y = s(400 + index * 215)
            label = str(graphic[f"{prefix}_label"])
            start = _number(graphic[f"{prefix}_start"])
            end = _number(graphic[f"{prefix}_end"])
            value = start + (end - start) * eased
            draw.text((left + s(30), y), label, font=label_font, fill="white")
            draw.text(
                (right - s(160), y + s(45)),
                str(round(value)),
                font=number_font,
                fill=color,
            )
            bar_width = max(
                s(12),
                round((right - left - s(230)) * min(1.0, value / max(1.0, start, end))),
            )
            draw.rounded_rectangle(
                (left + s(30), y + s(100), left + s(30) + bar_width, y + s(123)),
                radius=s(8),
                fill=color,
            )
    note = str(graphic["note"])
    for index, line in enumerate(_wrap(draw, note, label_font, width - 2 * left, 3)):
        draw.text((left, s(890 + index * 40)), line, font=label_font, fill="#b8c9e5")
    draw.rounded_rectangle(
        (left, height - s(250), right, height - s(85)), radius=s(20), fill="#061127"
    )
    for index, line in enumerate(
        _wrap(draw, caption, caption_font, width - 2 * left - s(48), 3)
    ):
        draw.text(
            (left + s(24), height - s(222) + index * s(45)),
            line,
            font=caption_font,
            fill="white",
        )
    draw.rectangle((left, height - s(38), right, height - s(28)), fill="#263b5c")
    draw.rectangle(
        (left, height - s(38), left + round((right - left) * progress), height - s(28)),
        fill="#fbbf24",
    )
    return image.tobytes()


class MotionGraphicsRenderer:
    """Render beat-level narrated graphics with an editable JSON visual plan."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        tts_provider: TtsProvider,
        plan_path: str | Path | None = None,
        ffmpeg: str = "ffmpeg",
        width: int = 720,
        height: int = 1280,
        fps: int = 24,
        bed_path: str | Path | None = None,
    ) -> None:
        if width < 720 or height * 9 != width * 16 or not 1 <= fps <= 60:
            raise ValueError("Motion graphics require a 9:16 frame and 1–60 fps.")
        self.output_dir = Path(output_dir)
        self.tts_provider = tts_provider
        self.plan_path = plan_path
        self.ffmpeg = ffmpeg
        self.width, self.height, self.fps = width, height, fps
        self.bed_path = Path(bed_path) if bed_path else None
        self.last_job: RenderJob | None = None

    def render(self, job: RenderJob) -> PublishedVideo:
        if job.status == RenderJobStatus.QUEUED:
            job = job.transition_to(RenderJobStatus.RUNNING).transition_to(
                RenderJobStatus.SUCCEEDED
            )
        elif job.status != RenderJobStatus.SUCCEEDED:
            raise ValueError("Only queued or succeeded render jobs can be rendered.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = job.job_id.replace(":", "_")
        output = self.output_dir / f"{stem}.mp4"
        plan = _prepare_plan(job, self.plan_path)
        (self.output_dir / f"{stem}.motion-plan.json").write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8"
        )
        beats = _timed_beats(job, plan)
        if not beats:
            raise ValueError("A motion graphics render requires storyboard beats.")
        captions = _captions(beats)
        _write_srt(self.output_dir / f"{stem}.srt", captions)
        total_seconds = sum(scene.duration_seconds for scene in job.storyboard.scenes)
        with tempfile.TemporaryDirectory() as temporary:
            narration = _audio_track(
                beats, self.tts_provider, Path(temporary), self.ffmpeg
            )
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{self.width}x{self.height}",
                "-r",
                str(self.fps),
                "-i",
                "pipe:0",
                "-i",
                str(narration),
            ]
            if self.bed_path is not None:
                if not self.bed_path.is_file():
                    raise FileNotFoundError(f"Audio bed not found: {self.bed_path}")
                command.extend(
                    [
                        "-stream_loop",
                        "-1",
                        "-i",
                        str(self.bed_path),
                        "-filter_complex",
                        "[2:a]volume=0.08[bed];[1:a][bed]amix=inputs=2:duration=first[a]",
                        "-map",
                        "0:v",
                        "-map",
                        "[a]",
                    ]
                )
            else:
                command.extend(["-map", "0:v", "-map", "1:a"])
            command.extend(
                [
                    "-t",
                    str(total_seconds),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(output),
                ]
            )
            with subprocess.Popen(
                command, stdin=subprocess.PIPE, stderr=subprocess.PIPE
            ) as process:
                assert process.stdin is not None and process.stderr is not None
                starts = [beat.start for beat in beats]
                caption_starts = [caption[0] for caption in captions]
                try:
                    for frame_index in range(total_seconds * self.fps):
                        now = frame_index / self.fps
                        beat = beats[max(0, bisect.bisect_right(starts, now) - 1)]
                        caption = captions[
                            max(0, bisect.bisect_right(caption_starts, now) - 1)
                        ][2]
                        progress = min(1.0, (now - beat.start) / beat.duration)
                        scene_number = next(
                            i
                            for i, scene in enumerate(job.storyboard.scenes, 1)
                            if scene.scene_id == beat.scene_id
                        )
                        process.stdin.write(
                            _frame(
                                beat,
                                progress,
                                caption,
                                self.width,
                                self.height,
                                scene_number,
                                len(job.storyboard.scenes),
                            )
                        )
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()
                errors = process.stderr.read().decode("utf-8", errors="replace")
                if process.wait() != 0:
                    raise RuntimeError(f"FFmpeg motion render failed: {errors.strip()}")
        self.last_job = job
        return publish_video(job, str(output))
