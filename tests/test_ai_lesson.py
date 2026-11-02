import json
import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Topic
from lattice.research import OllamaLessonProvider, create_configured_lesson_provider


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps({"response": json.dumps(self.value)}).encode()


class AiLessonTests(unittest.TestCase):
    def test_ollama_adapter_parses_structured_json(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        response = {
            "summary": "A concise lesson.",
            "uncertainty": "Examples are simplified.",
            "sections": [
                {"heading": heading, "text": f"Explanation of {heading}."}
                for heading in config.required_sections
            ],
            "claims": [
                {
                    "statement": "This is a model-generated claim.",
                    "evidence_level": "model-generated",
                    "uncertainty": "Simplified for a short lesson.",
                }
            ],
        }
        provider = OllamaLessonProvider(
            "test-model",
            opener=lambda *_args, **_kwargs: _Response(response),
        )
        lesson = provider.generate_lesson(Topic("Path dependence", "systems"), config)
        self.assertEqual(len(lesson.sections), len(config.required_sections))
        self.assertEqual(lesson.to_research_packet().sources[0].source_type, "ai-generated")

    def test_ollama_adapter_rejects_wrong_headings(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        provider = OllamaLessonProvider(
            "test-model",
            opener=lambda *_args, **_kwargs: _Response(
                {
                    "summary": "bad",
                    "uncertainty": "",
                    "sections": [{"heading": "Wrong", "text": "bad"}],
                    "claims": [{"statement": "claim"}],
                }
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "section headings"):
            provider.generate_lesson(Topic("Topic", "systems"), config)

    def test_configured_provider_uses_script_model_settings(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        provider = create_configured_lesson_provider(config)
        self.assertIsInstance(provider, OllamaLessonProvider)
        self.assertEqual(provider.model, "qwen3:4b")
        self.assertEqual(
            provider.endpoint, "http://127.0.0.1:11434/api/generate"
        )
