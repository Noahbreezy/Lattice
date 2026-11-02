import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Claim, ScriptSection, Topic
from lattice.pipeline import build_research_packet, build_script
from lattice.quality import check_lesson, check_script
from lattice.research import AILesson


class QualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        self.topic = Topic("A topic", "systems")
        self.research = build_research_packet(self.topic)

    def test_provisional_research_fails_quality_gate(self) -> None:
        report = check_script(
            self.config, self.research, build_script(self.config, self.research)
        )
        self.assertFalse(report.passed)
        self.assertIn("placeholder-source", {issue.code for issue in report.issues})
        self.assertIn("unverified-claim", {issue.code for issue in report.issues})

    def test_quality_report_accepts_matching_verified_packet(self) -> None:
        verified = self.research.__class__(
            topic=self.research.topic,
            summary=self.research.summary,
            sources=(
                self.research.sources[0].__class__(
                    self.research.sources[0].title,
                    "A real citation",
                    "https://example.com/source",
                    "paper",
                ),
            ),
            claims=(
                self.research.claims[0].__class__(
                    self.research.claims[0].statement,
                    "supported",
                    (0,),
                    "Scope remains limited.",
                ),
            ),
            created_at=self.research.created_at,
        )
        script = build_script(self.config, verified, words_per_minute=60)
        report = check_script(self.config, verified, script, duration_tolerance=1.0)
        self.assertTrue(report.passed)

    def test_lesson_quality_reports_content_risks(self) -> None:
        lesson = AILesson(
            topic=self.topic,
            summary="A summary.",
            sections=tuple(
                ScriptSection(heading, "Too short.")
                for heading in self.config.required_sections
            ),
            claims=(Claim("The claim is always true.", "model-generated", ()),),
            uncertainty="",
            provider_model="test/fake",
        )
        report = check_lesson(self.config, lesson)
        codes = {issue.code for issue in report.issues}
        self.assertIn("section-length", codes)
        self.assertIn("lesson-length", codes)
        self.assertIn("claim-count", codes)
        self.assertIn("uncertainty", codes)
        self.assertIn("unsupported-certainty", codes)
