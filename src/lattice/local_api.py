"""Small local review API built only on the Python standard library."""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from pathlib import Path

from .contracts import ReviewDecision, ReviewMarker
from .persistence import EpisodeRepository


class ReviewApiHandler(BaseHTTPRequestHandler):
    """HTTP adapter for local episode review and queue inspection."""

    repository: EpisodeRepository
    review_token: str = ""
    media_root: Path | None = None

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path == "/app":
            self._write_html(_REVIEW_APP)
            return
        if path == "/health":
            self._write(HTTPStatus.OK, {"status": "ok"})
            return
        if path.startswith("/media/"):
            self._serve_media(path.removeprefix("/media/"))
            return
        if path == "/episodes":
            self._write(
                HTTPStatus.OK,
                [self._episode_json(item) for item in self.repository.list_episodes()],
            )
            return
        if path == "/review-queue":
            self._write(
                HTTPStatus.OK,
                [self._episode_json(item) for item in self.repository.list_queue()],
            )
            return
        if path.startswith("/episodes/"):
            if path.endswith("/reviews"):
                episode_id = path.removeprefix("/episodes/").removesuffix("/reviews")
                if self.repository.get(episode_id) is None:
                    self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
                else:
                    self._write(
                        HTTPStatus.OK,
                        [self._review_json(review) for review in self.repository.reviews_for(episode_id)],
                    )
                return
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
            criteria_value = payload.get("criteria", [])
            if not isinstance(criteria_value, list):
                raise ValueError("criteria must be an array.")
            markers_value = payload.get("markers", [])
            if not isinstance(markers_value, list):
                raise ValueError("markers must be an array.")
            markers = tuple(
                ReviewMarker(
                    start_seconds=int(marker["start_seconds"]),
                    end_seconds=int(marker["end_seconds"]),
                    criterion=str(marker["criterion"]),
                    comment=str(marker.get("comment", "")),
                )
                for marker in markers_value
            )
            updated, review = self.repository.decide(
                episode, reviewer_id, decision, feedback,
                tuple(str(item) for item in criteria_value), markers,
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
                    "criteria": review.criteria,
                    "markers": [
                        {
                            "start_seconds": marker.start_seconds,
                            "end_seconds": marker.end_seconds,
                            "criterion": marker.criterion,
                            "comment": marker.comment,
                        }
                        for marker in review.markers
                    ],
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

    def _write_html(self, value: str) -> None:
        body = value.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_media(self, episode_id: str) -> None:
        if self.media_root is None:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Media serving is not configured."})
            return
        episode = self.repository.get(episode_id)
        if episode is None or not episode.final_video_uri:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Media not found."})
            return
        candidate = Path(episode.final_video_uri)
        if not candidate.is_absolute():
            candidate = self.media_root / candidate
        try:
            resolved = candidate.resolve()
            root = self.media_root.resolve()
            resolved.relative_to(root)
        except ValueError:
            self._write(HTTPStatus.FORBIDDEN, {"error": "Media path is outside storage."})
            return
        if not resolved.is_file():
            self._write(HTTPStatus.NOT_FOUND, {"error": "Media not found."})
            return
        body = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(resolved))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
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

    @staticmethod
    def _review_json(review: object) -> dict[str, object]:
        return {
            "episode_id": review.episode_id,
            "decision": review.decision.value,
            "reviewer_id": review.reviewer_id,
            "feedback": review.feedback,
            "criteria": review.criteria,
            "markers": [
                {
                    "start_seconds": marker.start_seconds,
                    "end_seconds": marker.end_seconds,
                    "criterion": marker.criterion,
                    "comment": marker.comment,
                }
                for marker in review.markers
            ],
            "created_at": review.created_at,
        }

    def log_message(self, format: str, *args: object) -> None:
        return


def create_review_server(
    repository: EpisodeRepository,
    host: str = "127.0.0.1",
    port: int = 8765,
    review_token: str | None = None,
    media_root: str | Path | None = None,
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
    handler.media_root = Path(media_root) if media_root is not None else None
    return ThreadingHTTPServer((host, port), handler)


_REVIEW_APP = """<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lattice review</title>
<style>
body{font:16px system-ui;background:#0f172a;color:#e2e8f0;max-width:640px;margin:auto;padding:16px}
video{width:100%;border-radius:16px;background:#020617}button,textarea{font:1rem;padding:12px;border-radius:10px}
button{border:0;margin:6px 4px 6px 0}.approve{background:#86efac}.reject{background:#fca5a5}
textarea{width:96%;min-height:80px}.card{background:#1e293b;padding:16px;border-radius:16px;margin-top:16px}
</style>
<h1>Lattice review</h1><p id="status">Loading queue…</p><main id="card"></main>
<script>
let item;
async function load(){const r=await fetch('/review-queue'); const q=await r.json(); item=q[0];
 if(!item){document.querySelector('#status').textContent='No videos waiting for processing.';return}
 document.querySelector('#status').textContent=item.topic+' · revision '+item.revision;
 document.querySelector('#card').innerHTML=`<div class="card"><video controls playsinline src="/media/${item.id}"></video>
 <p>Reject criteria (comma separated)</p><input id="criteria" placeholder="visual_clarity, pacing">
 <textarea id="feedback" placeholder="Optional feedback"></textarea><br>
 <label>Start <input id="start" type="number" min="0" value="0"></label>
 <label>End <input id="end" type="number" min="1" value="5"></label><br>
 <button class="approve" onclick="decide('approve')">Approve</button>
 <button class="reject" onclick="decide('reject')">Reject</button></div>`}
async function decide(decision){const criteria=document.querySelector('#criteria').value.split(',').map(x=>x.trim()).filter(Boolean);
 const feedback=document.querySelector('#feedback').value; const start=Number(document.querySelector('#start').value);
 const end=Number(document.querySelector('#end').value); const markers=criteria.length?[{start_seconds:start,end_seconds:end,criterion:criteria[0],comment:feedback}]:[];
 const r=await fetch('/episodes/'+item.id+'/review',{method:'POST',
 headers:{'Content-Type':'application/json'},body:JSON.stringify({decision,reviewer_id:'owner',criteria,markers,feedback})});
 if(!r.ok){alert((await r.json()).error);return} load()} load();
</script>"""
