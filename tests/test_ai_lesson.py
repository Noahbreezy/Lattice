import json
import unittest
from pathlib import Path

from lattice.config import load_config
from lattice.contracts import Topic
from lattice.research import (
    OllamaLessonProvider,
    _lesson_prompt,
    create_configured_lesson_provider,
)


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps({"response": json.dumps(self.value)}).encode()


class _CapturingOpener:
    def __init__(self, value):
        self.value = value
        self.request = None

    def __call__(self, request, **_kwargs):
        self.request = request
        return _Response(self.value)


class AiLessonTests(unittest.TestCase):
    def test_prompt_sets_a_maximum_without_padding_to_it(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        prompt = _lesson_prompt(Topic("Path dependence", "systems"), config)
        self.assertIn("shorter than 180 seconds", prompt)
        self.assertIn("only as long as needed", prompt)
        self.assertIn("Do not\n  pad", prompt)

    def test_ollama_adapter_parses_structured_json(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        response = {
            "summary": "A concise lesson.",
            "uncertainty": "Examples are simplified.",
            "sections": [
                {
                    "heading": heading,
                    "text": (
                        f"Explanation of {heading} with a concrete mechanism, "
                        "tradeoff, and carefully scoped example."
                    ),
                    "visual_description": (
                        f"Show the initial state, mechanism, and result for {heading} "
                        "in one continuous vertical shot, with a slow camera move, "
                        "grounded subjects, explanatory overlays, and a visual handoff "
                        "that preserves the location and palette for the next scene."
                    ),
                }
                for heading in config.required_sections
            ],
            "claims": [
                {
                    "statement": statement,
                    "evidence_level": "model-generated",
                    "uncertainty": "Simplified for a short lesson.",
                }
                for statement in (
                    "This is a model-generated claim.",
                    "A second claim explains the mechanism.",
                    "A third claim describes the practical implication.",
                )
            ],
        }
        opener = _CapturingOpener(response)
        provider = OllamaLessonProvider("test-model", opener=opener)
        lesson = provider.generate_lesson(Topic("Path dependence", "systems"), config)
        self.assertEqual(len(lesson.sections), len(config.required_sections))
        self.assertIn("continuous vertical shot", lesson.sections[0].visual_description)
        self.assertEqual(
            lesson.to_research_packet().sources[0].source_type, "ai-generated"
        )
        request_payload = json.loads(opener.request.data)
        self.assertIs(request_payload["think"], False)

    def test_ollama_adapter_rejects_missing_production_visuals(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        response = {
            "summary": "A concise lesson.",
            "uncertainty": "Examples are simplified.",
            "sections": [
                {
                    "heading": heading,
                    "text": "A useful explanation with a concrete mechanism and example.",
                    "visual_description": "Show something relevant.",
                }
                for heading in config.required_sections
            ],
            "claims": [
                {"statement": f"Substantive model claim number {index}."}
                for index in range(3)
            ],
        }
        provider = OllamaLessonProvider(
            "test-model", opener=lambda *_args, **_kwargs: _Response(response)
        )
        with self.assertRaisesRegex(RuntimeError, "visual description"):
            provider.generate_lesson(Topic("Path dependence", "systems"), config)

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

    def test_ollama_adapter_canonicalizes_minor_heading_variation(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        sections = []
        for heading in config.required_sections:
            sections.append(
                {
                    "heading": (
                        "Concrete example"
                        if heading == "A concrete example"
                        else heading
                    ),
                    "text": "A useful explanation with a concrete mechanism and example.",
                    "visual_description": (
                        "Establish a grounded subject in a vertical frame, move the camera "
                        "through the causal mechanism, animate a restrained explanatory "
                        "overlay, reveal the result, and preserve the location, lighting, "
                        "subject, and palette for the following scene."
                    ),
                }
            )
        provider = OllamaLessonProvider(
            "test-model",
            opener=lambda *_args, **_kwargs: _Response(
                {
                    "summary": "A concise lesson.",
                    "uncertainty": "Examples are simplified.",
                    "sections": sections,
                    "claims": [
                        {"statement": f"Substantive model claim number {index}."}
                        for index in range(3)
                    ],
                }
            ),
        )
        lesson = provider.generate_lesson(Topic("Topic", "systems"), config)
        self.assertEqual(
            tuple(section.heading for section in lesson.sections),
            config.required_sections,
        )

    def test_configured_provider_uses_script_model_settings(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        provider = create_configured_lesson_provider(config)
        self.assertIsInstance(provider, OllamaLessonProvider)
        self.assertEqual(provider.model, "qwen3:4b")
        self.assertEqual(provider.endpoint, "http://127.0.0.1:11434/api/generate")
