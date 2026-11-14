from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.request import Request
from unittest.mock import patch

from lattice.config import load_config
from lattice.contracts import (
    Claim,
    ResearchPacket,
    Review,
    ReviewDecision,
    ReviewMarker,
    Source,
    Topic,
)
from lattice.research import (
    OllamaLessonProvider,
    WikipediaResearchProvider,
    lesson_prompt,
    create_configured_lesson_provider,
    create_configured_research_provider,
)


class _Response:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        return None

    def read(self) -> bytes:
        return json.dumps({"response": json.dumps(self.value)}).encode()


class _CapturingOpener:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value
        self.request: Request | None = None

    def __call__(self, request: Request, **_kwargs: object) -> _Response:
        del _kwargs
        self.request = request
        return _Response(self.value)


class AiLessonTests(unittest.TestCase):
    def test_revision_prompt_includes_saved_review_context(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        response: dict[str, object] = {
            "summary": "A revised explanation.",
            "uncertainty": "This remains a simplified example.",
            "sections": [
                {
                    "heading": heading,
                    "text": "A clear revised explanation shows the cause, the mechanism, and the result in this example.",
                    "visual_description": "Show a grounded subject in a consistent navy setting. Animate the initial state and the causal mechanism, then reveal the resulting state with a slow camera move and a coherent handoff to the following scene.",
                }
                for heading in config.required_sections
            ],
            "claims": [
                {
                    "statement": f"Limited claim number {index}.",
                    "uncertainty": "Simplified.",
                }
                for index in range(3)
            ],
        }
        opener = _CapturingOpener(response)
        provider = OllamaLessonProvider("test-model", opener=opener)
        review = Review(
            "episode-1",
            ReviewDecision.REJECT,
            "owner",
            "Clarify the causal transition.",
            ("explanatory clarity",),
            (ReviewMarker(1, 3, "pacing", "Show the consequence sooner."),),
        )
        provider.generate_revision(Topic("Path dependence", "systems"), config, review)
        assert opener.request is not None and isinstance(opener.request.data, bytes)
        prompt = json.loads(opener.request.data)["prompt"]
        self.assertIn("Clarify the causal transition", prompt)
        self.assertIn("explanatory clarity", prompt)
        self.assertIn('"start_seconds": 1', prompt)
        self.assertIn("Show the consequence sooner", prompt)

    def test_prompt_sets_a_maximum_without_padding_to_it(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        prompt = lesson_prompt(Topic("Path dependence", "systems"), config)
        self.assertIn("no longer than 179 seconds", prompt)
        self.assertIn(config.lesson_prompt, prompt)
        self.assertIn("high information density without rushing", prompt)
        self.assertIn("only as long as needed", prompt)
        self.assertIn("Do not\n  pad", prompt)

    def test_ollama_adapter_parses_structured_json(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        response: dict[str, object] = {
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
        assert opener.request is not None and isinstance(opener.request.data, bytes)
        request_payload = json.loads(opener.request.data)
        self.assertIs(request_payload["think"], False)

    def test_ollama_adapter_rejects_missing_production_visuals(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        response: dict[str, object] = {
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
            "test-model", opener=_CapturingOpener(response)
        )
        with self.assertRaisesRegex(RuntimeError, "visual description"):
            provider.generate_lesson(Topic("Path dependence", "systems"), config)

    def test_ollama_adapter_rejects_wrong_headings(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        provider = OllamaLessonProvider(
            "test-model",
            opener=_CapturingOpener(
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
        sections: list[dict[str, str]] = []
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
            opener=_CapturingOpener(
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
        assert isinstance(provider, OllamaLessonProvider)
        self.assertEqual(provider.model, "qwen3:4b")
        self.assertEqual(provider.endpoint, "http://127.0.0.1:11434/api/generate")

    def test_configured_research_provider_selects_wikipedia(self):
        from dataclasses import replace

        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        tools = tuple(
            {**tool, "provider": "wikipedia", "required": True}
            if tool["name"] == "research assistant"
            else tool
            for tool in config.ai_tools
        )
        self.assertIsInstance(
            create_configured_research_provider(replace(config, ai_tools=tools)),
            WikipediaResearchProvider,
        )

    def test_configured_lesson_provider_loads_installed_adapter(self):
        from dataclasses import replace

        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        tools = tuple(
            {**tool, "provider": "custom"} if tool["name"] == "script model" else tool
            for tool in config.ai_tools
        )
        sentinel = object()
        def make_sentinel(*args: object) -> object:
            del args
            return sentinel
        with patch(
            "lattice.research.provider_factory", return_value=make_sentinel
        ):
            self.assertIs(
                create_configured_lesson_provider(replace(config, ai_tools=tools)),
                sentinel,
            )

    def test_grounded_lesson_retains_sources_without_self_verifying_claims(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        topic = Topic("A useful idea", "systems")
        packet = ResearchPacket(
            topic,
            "A sourced summary of the mechanism.",
            (
                Source(
                    "Reference",
                    "Reference citation",
                    "https://example.org/ref",
                    "reference",
                ),
            ),
            (Claim("A limited claim.", "supported", (0,)),),
            "2026-01-01T00:00:00Z",
        )
        response: dict[str, object] = {
            "summary": "A limited explanation.",
            "uncertainty": "The example is simplified.",
            "sections": [
                {
                    "heading": heading,
                    "text": "A useful example shows how a decision changes the next outcome in practice.",
                    "visual_description": "Show a grounded subject in a continuous vertical setting. Animate the starting state and causal mechanism, move the camera through the comparison, reveal the resulting state, and maintain subjects and lighting for the following scene.",
                }
                for heading in config.required_sections
            ],
            "claims": [
                {
                    "statement": f"A limited claim about mechanism {index}.",
                    "evidence_level": "model-generated",
                }
                for index in range(3)
            ],
        }
        opener = _CapturingOpener(response)
        lesson = OllamaLessonProvider(
            "test-model", opener=opener
        ).generate_grounded_lesson(
            topic,
            config,
            packet,
        )
        assert opener.request is not None and isinstance(opener.request.data, bytes)
        self.assertIn(
            "https://example.org/ref", json.loads(opener.request.data)["prompt"]
        )
        research = lesson.to_research_packet()
        self.assertEqual(research.sources[1], packet.sources[0])
        self.assertEqual(research.claims[0].source_indices, (0,))
