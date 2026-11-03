import tempfile
import unittest
import wave
from pathlib import Path

from lattice.contracts import Storyboard, StoryboardScene
from lattice.tts import Narration, _proportional_timings, reconcile_storyboard_timing


class TtsTests(unittest.TestCase):
    def test_word_timings_cover_audio_duration(self) -> None:
        timings = _proportional_timings(["one", "two", "three"], 3.0)
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
            _proportional_timings(["one", "two", "three", "four"], 7.6),
            "test",
        )
        reconciled = reconcile_storyboard_timing(storyboard, narration)
        self.assertEqual(sum(scene.duration_seconds for scene in reconciled.scenes), 8)
        self.assertEqual(
            tuple(scene.duration_seconds for scene in reconciled.scenes), (4, 4)
        )
        self.assertEqual(reconciled.version, storyboard.version + 1)
