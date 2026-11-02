import tempfile
import unittest
import wave
from pathlib import Path

from lattice.tts import _proportional_timings


class TtsTests(unittest.TestCase):
    def test_word_timings_cover_audio_duration(self) -> None:
        timings = _proportional_timings(["one", "two", "three"], 3.0)
        self.assertEqual(len(timings), 3)
        self.assertEqual(timings[0].start_seconds, 0)
        self.assertEqual(timings[-1].end_seconds, 3.0)
