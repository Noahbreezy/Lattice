import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from test_storage import FakeS3

from lattice.contracts import Episode, EpisodeStatus, Topic
from lattice.local_api import create_review_server
from lattice.persistence import EpisodeRepository
from lattice.storage import S3ObjectStorage


class LocalApiTests(unittest.TestCase):
    def test_strict_server_keeps_private_s3_media_behind_bearer_token(self) -> None:
        storage = S3ObjectStorage("review", client=FakeS3())
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "video.mp4"
            video_path.write_bytes(b"mp4")
            video = storage.put_file("videos/episode-1/revision-1.mp4", video_path)
            lesson = storage.put_json(
                "lessons/episode-1/revision-1.json", {"kind": "lesson"}
            )
            repository = EpisodeRepository()
            repository.save(
                Episode(
                    "episode-1",
                    Topic("A topic", "systems"),
                    EpisodeStatus.AWAITING_REVIEW,
                    1,
                    str(video.path),
                    lesson_uri=str(lesson.path),
                )
            )
            server = create_review_server(
                repository,
                port=0,
                review_token="secret",
                object_storage=storage,
                strict_auth=True,
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            try:
                connection.request("GET", "/media/episode-1")
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                headers = {"Authorization": "Bearer secret"}
                connection.request("GET", "/media/episode-1", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b"mp4")
                connection.request("GET", "/episodes/episode-1", headers=headers)
                response = connection.getresponse()
                self.assertIsNone(json.loads(response.read())["final_video_uri"])
                connection.request("GET", "/episodes/episode-1/lesson", headers=headers)
                response = connection.getresponse()
                self.assertEqual(json.loads(response.read())["kind"], "lesson")
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                repository.close()

    def test_mobile_review_app_and_queue_require_api_token(self) -> None:
        repository = EpisodeRepository()
        repository.save(
            Episode(
                "queued-video",
                Topic("A topic", "systems"),
                EpisodeStatus.AWAITING_REVIEW,
                1,
                "private://video.mp4",
            )
        )
        token = "local-review-token"
        server = create_review_server(repository, port=0, review_token=token)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/app")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        app = response.read()
        self.assertIn(b"playsinline", app)
        self.assertIn(b"Approve", app)
        self.assertIn(b"Reject", app)
        self.assertIn(b"fetch('/review-queue'", app)
        self.assertIn(b"fetch('/media/'", app)
        self.assertIn(b"response.blob()", app)
        self.assertIn(b"load()", app)
        connection.request("GET", "/review-queue")
        self.assertEqual(connection.getresponse().status, 401)
        connection.request(
            "GET",
            "/review-queue",
            headers={"Authorization": "Bearer " + token},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())[0]["id"], "queued-video")
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        repository.close()

    def test_review_api_requires_token_and_records_approval(self) -> None:
        repository = EpisodeRepository()
        episode = Episode(
            "episode-1",
            Topic("A topic", "systems"),
            EpisodeStatus.AWAITING_REVIEW,
            1,
            "private://video.mp4",
        )
        repository.save(episode)
        token = "local-review-token"
        server = create_review_server(repository, port=0, review_token=token)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/episodes")
        self.assertEqual(connection.getresponse().status, 401)
        body = json.dumps({"decision": "approve", "reviewer_id": "owner"}).encode()
        connection.request(
            "POST",
            "/episodes/episode-1/review",
            body=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(repository.get("episode-1").status, EpisodeStatus.APPROVED)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        repository.close()

    def test_non_loopback_server_requires_authentication(self) -> None:
        repository = EpisodeRepository()
        with self.assertRaisesRegex(ValueError, "token"):
            create_review_server(repository, host="0.0.0.0", port=0)
        repository.close()

    def test_rejection_accepts_criteria_and_timestamped_markers(self) -> None:
        repository = EpisodeRepository()
        episode = Episode(
            "episode-marked",
            Topic("A topic", "systems"),
            EpisodeStatus.AWAITING_REVIEW,
            1,
            "private://video.mp4",
        )
        repository.save(episode)
        server = create_review_server(repository, port=0, review_token="token")
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port)
        body = json.dumps(
            {
                "decision": "reject",
                "reviewer_id": "owner",
                "criteria": ["visual_clarity"],
                "markers": [
                    {
                        "start_seconds": 2,
                        "end_seconds": 8,
                        "criterion": "visual_clarity",
                        "comment": "Use a concrete example.",
                    }
                ],
            }
        ).encode()
        connection.request(
            "POST",
            "/episodes/episode-marked/review",
            body=body,
            headers={
                "Authorization": "Bearer token",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(
            repository.reviews_for("episode-marked")[0].criteria, ("visual_clarity",)
        )
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        repository.close()

    def test_media_route_serves_only_configured_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "episode.mp4"
            media.write_bytes(b"mp4")
            repository = EpisodeRepository()
            episode = Episode(
                "episode-media",
                Topic("A topic", "systems"),
                EpisodeStatus.AWAITING_REVIEW,
                1,
                str(media),
            )
            repository.save(episode)
            server = create_review_server(
                repository, port=0, review_token="token", media_root=directory
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            connection.request(
                "GET",
                "/media/episode-media",
                headers={"Authorization": "Bearer token"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"mp4")
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            repository.close()

    def test_episode_exposes_and_serves_structured_content_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lesson_path = root / "lessons" / "episode-content" / "revision-1.json"
            script_path = root / "scripts" / "episode-content" / "revision-1.json"
            lesson_path.parent.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            lesson_path.write_text(
                json.dumps({"kind": "lesson", "sections": [{"heading": "Hook"}]}),
                encoding="utf-8",
            )
            script_path.write_text(
                json.dumps({"kind": "script", "production_script": "# Script"}),
                encoding="utf-8",
            )
            repository = EpisodeRepository()
            repository.save(
                Episode(
                    "episode-content",
                    Topic("A topic", "systems"),
                    EpisodeStatus.PROCESSING,
                    1,
                    lesson_uri=str(lesson_path),
                    script_uri=str(script_path),
                )
            )
            server = create_review_server(
                repository, port=0, review_token="token", media_root=root
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            headers = {"Authorization": "Bearer token"}
            connection.request("GET", "/episodes/episode-content", headers=headers)
            episode_body = json.loads(connection.getresponse().read())
            self.assertEqual(
                episode_body["artifacts"]["lesson"],
                "/episodes/episode-content/lesson",
            )
            self.assertEqual(
                episode_body["artifacts"]["script"],
                "/episodes/episode-content/script",
            )
            connection.request(
                "GET", "/episodes/episode-content/lesson", headers=headers
            )
            self.assertEqual(
                json.loads(connection.getresponse().read())["kind"], "lesson"
            )
            connection.request(
                "GET", "/episodes/episode-content/script", headers=headers
            )
            self.assertEqual(
                json.loads(connection.getresponse().read())["kind"], "script"
            )
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            repository.close()

    def test_media_route_rejects_paths_outside_configured_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media_root = Path(directory) / "media"
            media_root.mkdir()
            outside = Path(directory) / "outside.mp4"
            outside.write_bytes(b"private")
            repository = EpisodeRepository()
            repository.save(
                Episode(
                    "episode-outside",
                    Topic("A topic", "systems"),
                    EpisodeStatus.AWAITING_REVIEW,
                    1,
                    str(outside),
                )
            )
            server = create_review_server(
                repository, port=0, review_token="token", media_root=media_root
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            connection.request(
                "GET",
                "/media/episode-outside",
                headers={"Authorization": "Bearer token"},
            )
            self.assertEqual(connection.getresponse().status, 403)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            repository.close()
