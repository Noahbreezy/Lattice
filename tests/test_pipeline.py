import json
import tempfile
import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Claim, ResearchPacket, Source, Topic
from lattice.history import LessonHistory
from lattice.pipeline import (
    build_demo_research_packet,
    build_production_bundle,
    build_research_packet,
    build_script,
    create_episode_draft,
    record_completed_episode,
    regenerate_scenes,
)
from lattice.research import AILesson, AILessonProvider
from lattice.contracts import ScriptSection


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

    def test_topic_is_reserved_when_draft_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            first_history = LessonHistory(path)
            second_history = LessonHistory(path)
            first = create_episode_draft(self.config, first_history)
            second = create_episode_draft(self.config, second_history)
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

    def test_production_bundle_allocates_exact_target_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = LessonHistory(Path(directory) / "history.json")
            bundle = build_production_bundle(self.config, history, offline=True)
            self.assertEqual(
                sum(scene.duration_seconds for scene in bundle.storyboard.scenes),
                self.config.video_length_seconds,
            )

    def test_demo_research_has_real_source_links(self) -> None:
        packet = build_demo_research_packet(Topic("Path dependence", "systems"))
        self.assertTrue(all(source.url.startswith("https://") for source in packet.sources))
        self.assertTrue(all(claim.evidence_level == "supported" for claim in packet.claims))

    def test_scene_regeneration_preserves_unaffected_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = LessonHistory(Path(directory) / "history.json")
            bundle = build_production_bundle(self.config, history, offline=True)
            revised = regenerate_scenes(
                bundle.storyboard, {"scene-2"}, "Use a concrete railway example."
            )
            self.assertEqual(revised.version, bundle.storyboard.version + 1)
            self.assertEqual(
                revised.scenes[0].visual_direction,
                bundle.storyboard.scenes[0].visual_direction,
            )
            self.assertIn("railway", revised.scenes[1].visual_direction)

    def test_ai_lesson_provider_drives_script_sections(self) -> None:
        class FakeLessonProvider:
            def generate_lesson(self, topic, config):
                return AILesson(
                    topic=topic,
                    summary="A model-authored lesson.",
                    sections=tuple(
                        ScriptSection(
                            heading,
                            f"Model explanation of {heading} with a concrete example and mechanism.",
                        )
                        for heading in config.required_sections
                    ),
                    claims=(
                        Claim("The concept has an important mechanism.", "model-generated", ()),
                        Claim("A second claim describes a useful tradeoff.", "model-generated", ()),
                        Claim("A third claim explains why the example matters.", "model-generated", ()),
                    ),
                    uncertainty="This is recreational model-generated content.",
                    provider_model="test/fake",
                )

        with tempfile.TemporaryDirectory() as directory:
            bundle = build_production_bundle(
                self.config,
                LessonHistory(Path(directory) / "history.json"),
                lesson_provider=FakeLessonProvider(),
            )
            self.assertEqual(
                bundle.draft.script.sections[0].text,
                "Model explanation of The idea with a concrete example and mechanism.",
            )
            self.assertEqual(bundle.draft.research.sources[0].source_type, "ai-generated")
