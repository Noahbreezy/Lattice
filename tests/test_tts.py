import tempfile
import unittest
import wave
from pathlib import Path

from lattice.contracts import Storyboard, StoryboardScene
from lattice.renderer import FfmpegRenderer
from lattice.tts import (
    Narration,
    WindowsSpeechTts,
    proportional_timings,
    reconcile_storyboard_timing,
    validate_narration,
)


class TtsTests(unittest.TestCase):
    def test_word_timings_cover_audio_duration(self) -> None:
        timings = proportional_timings(["one", "two", "three"], 3.0)
        self.assertEqual(len(timings), 3)
        self.assertEqual(timings[0].start_seconds, 0)
        self.assertEqual(timings[-1].end_seconds, 3.0)

    def test_reconcile_storyboard_uses_measured_audio_duration(self) -> None:
        storyboard = Storyboard(
            (
                StoryboardScene("one", "One", "one two", "visual one", 5),
                StoryboardScene("two", "Two", "three four", "visual two", 5),
            )
        )
        narration = Narration(
            "narration.wav",
            7.6,
            proportional_timings(["one", "two", "three", "four"], 7.6),
            "test",
        )
        reconciled = reconcile_storyboard_timing(storyboard, narration)
        self.assertEqual(sum(scene.duration_seconds for scene in reconciled.scenes), 8)
        self.assertEqual(
            tuple(scene.duration_seconds for scene in reconciled.scenes), (4, 4)
        )
        self.assertEqual(reconciled.version, storyboard.version + 1)

    def test_reconcile_storyboard_rejects_narration_over_maximum(self) -> None:
        storyboard = Storyboard(
            (StoryboardScene("one", "One", "one two", "visual one", 8),),
            maximum_duration_seconds=8,
        )
        narration = Narration(
            "narration.wav",
            8.6,
            proportional_timings(["one", "two"], 8.6),
            "test",
        )
        with self.assertRaisesRegex(ValueError, "duration exceeds"):
            reconcile_storyboard_timing(storyboard, narration)

    def test_windows_tts_rejects_empty_text_explicitly(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "empty"),
        ):
            WindowsSpeechTts().synthesize("", Path(directory) / "speech.wav")

    def test_renderer_defaults_to_windows_offline_tts(self) -> None:
        self.assertIsInstance(
            FfmpegRenderer("var/test-output").tts_provider, WindowsSpeechTts
        )

    def test_silent_wav_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silent.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 8000)
            narration = Narration(
                str(path), 1.0, proportional_timings(["hello"], 1.0), "test"
            )
            with self.assertRaisesRegex(RuntimeError, "silent"):
                validate_narration(narration)
