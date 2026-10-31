import json
import tempfile
import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Claim, ResearchPacket, Source, Topic
from lattice.history import LessonHistory
from lattice.pipeline import (
    build_research_packet,
    build_script,
    create_episode_draft,
    record_completed_episode,
)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )

    def test_pipeline_selects_topic_and_preserves_claim_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = LessonHistory(Path(directory) / "history.json")
            draft = create_episode_draft(self.config, history)
            self.assertEqual(draft.topic.title, self.config.topic_seeds[0]["title"])
            self.assertEqual(draft.research.claims[0].source_indices, (0,))
            self.assertEqual(
                len(draft.script.sections), len(self.config.required_sections)
            )
            self.assertGreater(draft.script.estimated_duration_seconds, 0)

    def test_completed_topic_is_not_selected_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = LessonHistory(Path(directory) / "history.json")
            first = create_episode_draft(self.config, history)
            record_completed_episode(first, history)
            second = create_episode_draft(self.config, history)
            self.assertNotEqual(first.topic.key, second.topic.key)

    def test_history_is_persisted_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "history.json"
            history = LessonHistory(path)
            history.record(Topic("A New Topic!", "history"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), ["a new topic"])

    def test_invalid_claim_source_link_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            ResearchPacket(
                topic=Topic("Topic", "subject"),
                summary="Summary",
                sources=(
                    Source("Source", "Citation", "https://example.com", "paper"),
                ),
                claims=(Claim("Claim", "supported", (1,)),),
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_script_duration_uses_word_count(self) -> None:
        topic = Topic("Topic", "subject")
        research = build_research_packet(topic)
        script = build_script(self.config, research, words_per_minute=60)
        self.assertEqual(
            script.estimated_duration_seconds,
            max(1, round(sum(len(section.text.split()) for section in script.sections))),
        )
