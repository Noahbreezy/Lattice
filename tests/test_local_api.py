import json
import unittest
import tempfile
from pathlib import Path
from http.client import HTTPConnection
from threading import Thread

from lattice.contracts import Episode, EpisodeStatus, Topic
from lattice.local_api import create_review_server
from lattice.persistence import EpisodeRepository


class LocalApiTests(unittest.TestCase):
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
        body = json.dumps({
            "decision": "reject",
            "reviewer_id": "owner",
            "criteria": ["visual_clarity"],
            "markers": [{
                "start_seconds": 2,
                "end_seconds": 8,
                "criterion": "visual_clarity",
                "comment": "Use a concrete example.",
            }],
        }).encode()
        connection.request(
            "POST",
            "/episodes/episode-marked/review",
            body=body,
            headers={"Authorization": "Bearer token", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(repository.reviews_for("episode-marked")[0].criteria, ("visual_clarity",))
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
