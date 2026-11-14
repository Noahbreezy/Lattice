"""Production, review, rejection, and rerender through the local adapters."""

import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from lattice.config import ProjectConfig, load_config
from lattice.contracts import Claim, EpisodeStatus, Review, ScriptSection, Topic
from lattice.history import LessonHistory
from lattice.local_api import create_review_server
from lattice.persistence import EpisodeRepository
from lattice.research import AILesson
from lattice.runner import run_next_episode


class RevisionProvider:
    review: Review | None = None

    def generate_lesson(self, topic: Topic, config: ProjectConfig) -> AILesson:
        return self._lesson(topic, config, "original")

    def generate_revision(self, topic: Topic, config: ProjectConfig, review: Review) -> AILesson:
        self.review = review
        return self._lesson(topic, config, "revised")

    @staticmethod
    def _lesson(topic: Topic, config: ProjectConfig, version: str) -> AILesson:
        return AILesson(
            topic=topic,
            summary=f"A {version} explanation of {topic.title}.",
            sections=tuple(
                ScriptSection(
                    heading,
                    f"The {version} explanation shows how a choice changes the next outcome, with a concrete example and a clear consequence.",
                    "Show a person making a choice in a consistent navy and amber setting. "
                    "Animate the cause, reveal the resulting state, use a slow camera move, "
                    "and preserve the same visual subjects and setting for the next scene.",
                )
                for heading in config.required_sections
            ),
            claims=tuple(
                Claim(
                    f"Claim {index} explains one limited consequence.",
                    "model-generated",
                    (),
                    "The example is simplified.",
                )
                for index in range(3)
            ),
            uncertainty="The example is simplified for a short lesson.",
            provider_model="test/revision-provider",
        )


class EndToEndTests(unittest.TestCase):
    def test_production_review_rejection_and_rerender(self):
        config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = EpisodeRepository(root / "review.sqlite")
            provider = RevisionProvider()
            history = LessonHistory(root / "history.json")
            output = root / "artifacts"
            first = run_next_episode(
                config, repository, history, output, lesson_provider=provider
            )
            self.assertEqual(first.status, EpisodeStatus.AWAITING_REVIEW)
            first_video = Path(first.final_video_uri)
            first_lesson = Path(first.lesson_uri)
            first_script = Path(first.script_uri)
            original_video = first_video.read_bytes()
            self.assertIn("original", first_script.read_text(encoding="utf-8"))

            server = create_review_server(
                repository,
                port=0,
                review_token="test-token",
                media_root=output / "review-media",
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            headers = {"Authorization": "Bearer test-token"}
            try:
                for kind in ("lesson", "script"):
                    connection.request(
                        "GET", f"/episodes/{first.id}/{kind}", headers=headers
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["kind"], kind)
                connection.request("GET", f"/media/{first.id}", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), original_video)
                body = json.dumps(
                    {
                        "decision": "reject",
                        "reviewer_id": "owner",
                        "feedback": "Clarify the causal transition.",
                        "criteria": ["explanatory clarity"],
                        "markers": [
                            {
                                "start_seconds": 1,
                                "end_seconds": 3,
                                "criterion": "pacing",
                                "comment": "Show the consequence sooner.",
                            }
                        ],
                    }
                ).encode()
                connection.request(
                    "POST",
                    f"/episodes/{first.id}/review",
                    body=body,
                    headers={**headers, "Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.read())["episode"]["status"], "rejected"
                )

                second = run_next_episode(
                    config, repository, history, output, lesson_provider=provider
                )
                self.assertEqual(second.id, first.id)
                self.assertEqual(second.revision, 2)
                self.assertEqual(second.status, EpisodeStatus.AWAITING_REVIEW)
                assert provider.review is not None
                self.assertEqual(provider.review.criteria, ("explanatory clarity",))
                self.assertEqual(provider.review.markers[0].start_seconds, 1)
                self.assertIn(
                    "revised", Path(second.script_uri).read_text(encoding="utf-8")
                )
                self.assertNotEqual(second.final_video_uri, first.final_video_uri)
                self.assertEqual(first_video.read_bytes(), original_video)
                prior = repository.artifacts_for_revision(first.id, 1)
                assert prior is not None
                self.assertEqual(prior.video_uri, first.final_video_uri)
                self.assertEqual(prior.lesson_uri, first.lesson_uri)
                self.assertEqual(prior.script_uri, first.script_uri)
                self.assertTrue(first_lesson.is_file())
                self.assertTrue(first_script.is_file())
                self.assertTrue(
                    (
                        output / "episodes" / first.id / "revision-1" / "manifest.json"
                    ).is_file()
                )
                self.assertTrue(
                    (
                        output / "episodes" / first.id / "revision-2" / "evidence.json"
                    ).is_file()
                )
                revised_bundle = (
                    output / "episodes" / first.id / "revision-2" / "bundle.json"
                ).read_text(encoding="utf-8")
                self.assertIn("Clarify the causal transition", revised_bundle)
                self.assertIn(
                    "1-3s (pacing): Show the consequence sooner", revised_bundle
                )
                saved_feedback = json.loads(
                    repository.revisions_for(first.id)[1].feedback
                )
                self.assertEqual(saved_feedback["criteria"], ["explanatory clarity"])
                connection.request(
                    "GET", f"/episodes/{first.id}/revisions", headers=headers
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(len(json.loads(response.read())), 2)
                connection.request(
                    "GET", f"/media/{first.id}/revision-1", headers=headers
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), original_video)
                connection.request(
                    "GET", f"/episodes/{first.id}/revisions/1/script", headers=headers
                )
                response = connection.getresponse()
                self.assertEqual(json.loads(response.read())["revision"], 1)
                for kind in ("lesson", "script"):
                    connection.request(
                        "GET", f"/episodes/{first.id}/{kind}", headers=headers
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["revision"], 2)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                repository.close()
