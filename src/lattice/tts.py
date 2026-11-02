"""Provider-neutral local narration and timing adapters."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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
        return _estimated_narration(output, text, "piper")


class WindowsSpeechTts:
    """Zero-cost Windows SAPI adapter available without a Python dependency."""

    def __init__(self, voice: str = "", rate: int = 0) -> None:
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str, output_path: str | Path) -> Narration:
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
            completed = subprocess.run(
                [
                    "powershell",
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
            raise RuntimeError(f"Windows speech synthesis failed: {completed.stderr.strip()}")
        return _estimated_narration(output, text, "windows-sapi")


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


def _proportional_timings(words: list[str], duration: float) -> tuple[WordTiming, ...]:
    if not words:
        return ()
    step = duration / len(words)
    return tuple(
        WordTiming(word, index * step, (index + 1) * step)
        for index, word in enumerate(words)
    )
