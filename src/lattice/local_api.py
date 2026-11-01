"""Small local review API built only on the Python standard library."""

from __future__ import annotations

import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .contracts import ReviewDecision
from .persistence import EpisodeRepository


class ReviewApiHandler(BaseHTTPRequestHandler):
    """HTTP adapter for local episode review and queue inspection."""

    repository: EpisodeRepository
    review_token: str = ""

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path == "/health":
            self._write(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/episodes":
            self._write(
                HTTPStatus.OK,
                [self._episode_json(item) for item in self.repository.list_episodes()],
            )
            return
        if path.startswith("/episodes/"):
            episode = self.repository.get(path.removeprefix("/episodes/"))
            if episode is None:
                self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
            else:
                self._write(HTTPStatus.OK, self._episode_json(episode))
            return
        self._write(HTTPStatus.NOT_FOUND, {"error": "Route not found."})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if not path.startswith("/episodes/") or not path.endswith("/review"):
            self._write(HTTPStatus.NOT_FOUND, {"error": "Route not found."})
            return
        episode_id = path.removeprefix("/episodes/").removesuffix("/review")
        episode = self.repository.get(episode_id)
        if episode is None:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
            return
        try:
            payload = self._read_json()
            decision = ReviewDecision(payload["decision"])
            reviewer_id = str(payload["reviewer_id"]).strip()
            feedback = str(payload.get("feedback", ""))
            updated, review = self.repository.decide(
                episode, reviewer_id, decision, feedback
            )
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._write(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._write(
            HTTPStatus.OK,
            {
                "episode": self._episode_json(updated),
                "review": {
                    "decision": review.decision.value,
                    "reviewer_id": review.reviewer_id,
                    "feedback": review.feedback,
                    "created_at": review.created_at,
                },
            },
        )

    def _authorized(self) -> bool:
        if not self.review_token:
            return True
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.review_token
        if hmac.compare_digest(supplied, expected):
            return True
        self._write(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required."})
        return False

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64 * 1024:
            raise ValueError("Request body is too large.")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be an object.")
        return value

    def _write(self, status: HTTPStatus, value: object) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _episode_json(episode: object) -> dict[str, object]:
        return {
            "id": episode.id,
            "topic": episode.topic.title,
            "subject_area": episode.topic.subject_area,
            "status": episode.status.value,
            "revision": episode.revision,
            "final_video_uri": episode.final_video_uri,
            "created_at": episode.created_at,
        }

    def log_message(self, format: str, *args: object) -> None:
        return


def create_review_server(
    repository: EpisodeRepository,
    host: str = "127.0.0.1",
    port: int = 8765,
    review_token: str | None = None,
) -> ThreadingHTTPServer:
    """Create a local review server with safe binding defaults."""

    token = review_token if review_token is not None else os.getenv(
        "LATTICE_REVIEW_TOKEN", ""
    )
    if host not in {"127.0.0.1", "::1", "localhost"} and not token:
        raise ValueError("A review token is required when binding beyond localhost.")
    handler = type("ConfiguredReviewApiHandler", (ReviewApiHandler,), {})
    handler.repository = repository
    handler.review_token = token
    return ThreadingHTTPServer((host, port), handler)
