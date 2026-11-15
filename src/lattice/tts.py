"""Provider-neutral local narration and timing adapters."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import tempfile
import wave
from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from .contracts import SceneBeat, Storyboard, StoryboardScene


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class Narration:
    audio_uri: str
    duration_seconds: float
    timings: tuple[WordTiming, ...]
    provider: str


class TtsProvider(Protocol):
    def synthesize(self, text: str, output_path: str | Path) -> Narration:
        """Create a WAV narration and return timing metadata."""
        ...


class _KokoroEngine(Protocol):
    def create(
        self, text: str, *, voice: str, speed: float, lang: str
    ) -> tuple[Iterable[float], int]: ...


def validate_narration(narration: Narration) -> Narration:
    """Reject missing, empty, or silent audio from any local provider."""

    path = Path(narration.audio_uri)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("TTS provider did not produce an audio file.")
    if narration.duration_seconds <= 0 or _audio_is_silent(path):
        raise RuntimeError("TTS provider produced silent or zero-duration audio.")
    if not narration.timings:
        raise RuntimeError("TTS provider did not return word timings.")
    return narration


def reconcile_storyboard_timing(
    storyboard: Storyboard, narration: Narration
) -> Storyboard:
    """Resize scenes to the measured narration while preserving scene order."""

    if narration.duration_seconds <= 0:
        raise ValueError("Narration duration must be positive.")
    if not narration.timings:
        raise ValueError("Narration must include word timings.")
    target_seconds = max(len(storyboard.scenes), round(narration.duration_seconds))
    word_counts = [max(1, len(scene.narration.split())) for scene in storyboard.scenes]
    total_words = sum(word_counts)
    exact = [target_seconds * count / total_words for count in word_counts]
    durations = [max(1, int(value)) for value in exact]
    while sum(durations) < target_seconds:
        index = max(
            range(len(durations)),
            key=lambda item: exact[item] - durations[item],
        )
        durations[index] += 1
    while sum(durations) > target_seconds:
        index = max(
            (item for item, duration in enumerate(durations) if duration > 1),
            key=lambda item: durations[item] - exact[item],
        )
        durations[index] -= 1
    scenes = tuple(
        StoryboardScene(
            scene_id=scene.scene_id,
            script_section_heading=scene.script_section_heading,
            narration=scene.narration,
            visual_direction=scene.visual_direction,
            duration_seconds=durations[index],
            timing_sync=_retime_beats(scene.timing_sync, durations[index]),
        )
        for index, scene in enumerate(storyboard.scenes)
    )
    return Storyboard(
        scenes=scenes,
        version=storyboard.version + 1,
        provenance=storyboard.provenance,
        maximum_duration_seconds=storyboard.maximum_duration_seconds,
    )


def _retime_beats(
    beats: tuple[SceneBeat, ...], duration_seconds: int
) -> tuple[SceneBeat, ...]:
    if not beats:
        return ()
    count = min(len(beats), duration_seconds)
    boundaries = [round(index * duration_seconds / count) for index in range(count + 1)]
    return tuple(
        SceneBeat(
            boundaries[index],
            boundaries[index + 1],
            beats[index].visual,
            beats[index].narration_excerpt,
        )
        for index in range(count)
    )


class PiperTts:
    """Optional adapter for a locally installed Piper executable and model."""

    def __init__(self, model: str | Path, executable: str = "piper") -> None:
        self.model = str(model)
        self.executable = executable

    def synthesize(self, text: str, output_path: str | Path) -> Narration:
        if shutil.which(self.executable) is None:
            raise RuntimeError(
                "Piper is not installed. Install Piper and a voice model, or use "
                "WindowsSpeechTts."
            )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [self.executable, "--model", self.model, "--output_file", str(output)],
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Piper narration failed: {completed.stderr.strip()}")
        return validate_narration(_estimated_narration(output, text, "piper"))


class KokoroTts:
    """Offline Kokoro ONNX narration with a model loaded once per renderer."""

    def __init__(
        self,
        model: str | Path,
        voices: str | Path,
        *,
        voice: str = "am_michael",
        speed: float = 1.0,
    ) -> None:
        self.model = Path(model)
        self.voices = Path(voices)
        self.voice = voice
        self.speed = speed
        self._engine: _KokoroEngine | None = None
        if speed <= 0:
            raise ValueError("Kokoro speed must be positive.")

    def synthesize(self, text: str, output_path: str | Path) -> Narration:
        if not text.strip():
            raise ValueError("Cannot synthesize empty narration.")
        for path in (self.model, self.voices):
            if not path.is_file():
                raise RuntimeError(f"Kokoro model file not found: {path}")
        try:
            constructor = cast(
                Callable[[str, str], _KokoroEngine],
                import_module("kokoro_onnx").__dict__["Kokoro"],
            )
        except ImportError as exc:
            raise RuntimeError(
                "Kokoro ONNX is not installed in this Python environment."
            ) from exc
        engine = self._engine
        if engine is None:
            engine = constructor(str(self.model), str(self.voices))
            self._engine = engine
        samples, sample_rate = engine.create(
            text, voice=self.voice, speed=self.speed, lang="en-us"
        )
        pcm = array(
            "h",
            (round(max(-1.0, min(1.0, float(sample))) * 32767) for sample in samples),
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate))
            wav.writeframes(pcm.tobytes())
        return validate_narration(_estimated_narration(output, text, "kokoro-onnx"))


class WindowsSpeechTts:
    """Zero-cost Windows SAPI adapter available without a Python dependency."""

    def __init__(self, voice: str = "", rate: int = 0) -> None:
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str, output_path: str | Path) -> Narration:
        if not text.strip():
            raise ValueError("Cannot synthesize empty narration.")
        if platform.system() != "Windows" and shutil.which("powershell") is None:
            raise RuntimeError(
                "WindowsSpeechTts requires Windows PowerShell and System.Speech; "
                "no cloud TTS fallback is available."
            )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            text_path = Path(directory) / "narration.txt"
            script_path = Path(directory) / "speak.ps1"
            text_path.write_text(text, encoding="utf-8")
            voice = self.voice.replace("'", "''")
            script_path.write_text(
                "$ErrorActionPreference = 'Stop'\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                f"$s.Rate = {self.rate}\n"
                + (f"$s.SelectVoice('{voice}')\n" if voice else "")
                + "$s.SetOutputToWaveFile($args[1])\n"
                "$s.Speak([IO.File]::ReadAllText($args[0]))\n"
                "$s.Dispose()\n",
                encoding="utf-8",
            )
            powershell = shutil.which("powershell") or shutil.which("powershell.exe")
            if powershell is None:
                raise RuntimeError("Windows PowerShell executable was not found.")
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script_path),
                    str(text_path),
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Windows speech synthesis failed: {completed.stderr.strip()}"
            )
        return validate_narration(_estimated_narration(output, text, "windows-sapi"))


def _estimated_narration(path: Path, text: str, provider: str) -> Narration:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("TTS provider did not produce an audio file.")
    duration = _wav_duration(path)
    words = re.findall(r"\S+", text)
    timings = _proportional_timings(words, duration)
    return Narration(str(path), duration, timings, provider)


def _wav_duration(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / max(1, wav.getframerate())


def _audio_is_silent(path: Path) -> bool:
    import wave

    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        # PCM silence is all-zero samples. This avoids optional audio packages
        # while still rejecting the common silent-provider failure.
        return not frames or not any(frames)


def _proportional_timings(words: list[str], duration: float) -> tuple[WordTiming, ...]:
    if not words:
        return ()
    step = duration / len(words)
    return tuple(
        WordTiming(word, index * step, (index + 1) * step)
        for index, word in enumerate(words)
    )


proportional_timings = _proportional_timings
