import json
import unittest
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
