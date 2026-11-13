"""Small local review API built only on the Python standard library."""

from __future__ import annotations

import hmac
import ipaddress
import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .contracts import Episode, Review, ReviewDecision, ReviewMarker
from .persistence import EpisodeRepository
from .storage import ObjectStorage


class ReviewApiHandler(BaseHTTPRequestHandler):
    """HTTP adapter for local episode review and queue inspection."""

    repository: EpisodeRepository
    review_token: str = ""
    media_root: Path | None = None
    object_storage: ObjectStorage | None = None
    strict_auth: bool = False
    owner_id: str = "owner"

    def do_GET(self) -> None:
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
            historical = re.fullmatch(r"/media/([^/]+)/revision-(\d+)", path)
            if historical:
                self._serve_media(historical.group(1), int(historical.group(2)))
            else:
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
                [
                    self._episode_json(item)
                    for item in self.repository.list_review_queue()
                ],
            )
            return
        if path.startswith("/episodes/"):
            historical_artifact = re.fullmatch(
                r"/episodes/([^/]+)/revisions/(\d+)/(lesson|script)", path
            )
            if historical_artifact:
                self._serve_artifact(
                    historical_artifact.group(1),
                    historical_artifact.group(3),
                    int(historical_artifact.group(2)),
                )
                return
            revisions = re.fullmatch(r"/episodes/([^/]+)/revisions", path)
            if revisions:
                episode_id = revisions.group(1)
                if self.repository.get(episode_id) is None:
                    self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
                else:
                    self._write(
                        HTTPStatus.OK,
                        [
                            {
                                "revision": item.revision,
                                "video": f"/media/{episode_id}/revision-{item.revision}",
                                "lesson": f"/episodes/{episode_id}/revisions/{item.revision}/lesson",
                                "script": f"/episodes/{episode_id}/revisions/{item.revision}/script",
                            }
                            for item in self.repository.list_revision_artifacts(
                                episode_id
                            )
                        ],
                    )
                return
            for artifact_kind in ("lesson", "script"):
                suffix = f"/{artifact_kind}"
                if path.endswith(suffix):
                    episode_id = path.removeprefix("/episodes/").removesuffix(suffix)
                    self._serve_artifact(episode_id, artifact_kind)
                    return
            if path.endswith("/reviews"):
                episode_id = path.removeprefix("/episodes/").removesuffix("/reviews")
                if self.repository.get(episode_id) is None:
                    self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
                else:
                    self._write(
                        HTTPStatus.OK,
                        [
                            self._review_json(review)
                            for review in self.repository.reviews_for(episode_id)
                        ],
                    )
                return
            episode = self.repository.get(path.removeprefix("/episodes/"))
            if episode is None:
                self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
            else:
                self._write(HTTPStatus.OK, self._episode_json(episode))
            return
        self._write(HTTPStatus.NOT_FOUND, {"error": "Route not found."})

    def do_POST(self) -> None:
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
            reviewer_id = (
                self.owner_id
                if self.strict_auth
                else str(payload["reviewer_id"]).strip()
            )
            feedback = str(payload.get("feedback", ""))
            criteria_value = payload.get("criteria", [])
            if not isinstance(criteria_value, list):
                raise TypeError("criteria must be an array.")
            markers_value = payload.get("markers", [])
            if not isinstance(markers_value, list):
                raise TypeError("markers must be an array.")
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
                episode,
                reviewer_id,
                decision,
                feedback,
                tuple(str(item) for item in criteria_value),
                markers,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
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
        path = urlparse(self.path).path
        # A browser can load the local shell and media element without adding
        # headers; all state-changing and JSON routes remain bearer-protected.
        if path == "/app":
            return True
        if not self.strict_auth and path.startswith("/media/"):
            try:
                if ipaddress.ip_address(self.client_address[0]).is_loopback:
                    return True
            except ValueError:
                pass
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.review_token
        if hmac.compare_digest(supplied, expected):
            return True
        self._write(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required."})
        return False

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 64 * 1024:
            raise ValueError("Request body must be between 1 and 65536 bytes.")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise TypeError("Request body must be an object.")
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

    def _serve_media(self, episode_id: str, revision: int | None = None) -> None:
        if self.media_root is None and self.object_storage is None:
            self._write(
                HTTPStatus.NOT_FOUND, {"error": "Media serving is not configured."}
            )
            return
        episode = self.repository.get(episode_id)
        artifacts = (
            self.repository.artifacts_for_revision(episode_id, revision)
            if revision is not None
            else None
        )
        uri = (
            artifacts.video_uri
            if artifacts is not None
            else (
                episode.final_video_uri
                if revision is None and episode is not None
                else ""
            )
        )
        if not uri:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Media not found."})
            return
        if self.object_storage is not None:
            try:
                body = self.object_storage.get_bytes(uri)
            except (OSError, ValueError, KeyError):
                self._write(HTTPStatus.NOT_FOUND, {"error": "Media not found."})
                return
            self._write_binary(body, "video/mp4")
            return
        candidate = Path(uri)
        if not candidate.is_absolute():
            candidate = self.media_root / candidate
        try:
            resolved = candidate.resolve()
            root = self.media_root.resolve()
            resolved.relative_to(root)
        except ValueError:
            self._write(
                HTTPStatus.FORBIDDEN, {"error": "Media path is outside storage."}
            )
            return
        if not resolved.is_file():
            self._write(HTTPStatus.NOT_FOUND, {"error": "Media not found."})
            return
        self._write_binary(
            resolved.read_bytes(),
            mimetypes.guess_type(str(resolved))[0] or "application/octet-stream",
        )

    def _write_binary(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _serve_artifact(
        self, episode_id: str, artifact_kind: str, revision: int | None = None
    ) -> None:
        """Serve a structured private artifact through an authenticated route."""

        if self.media_root is None and self.object_storage is None:
            self._write(
                HTTPStatus.NOT_FOUND, {"error": "Artifact serving is not configured."}
            )
            return
        episode = self.repository.get(episode_id)
        if episode is None:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Episode not found."})
            return
        artifacts = (
            self.repository.artifacts_for_revision(episode_id, revision)
            if revision is not None
            else None
        )
        if revision is not None and artifacts is None:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Artifact not found."})
            return
        source = artifacts if artifacts is not None else episode
        uri = source.lesson_uri if artifact_kind == "lesson" else source.script_uri
        if not uri:
            self._write(HTTPStatus.NOT_FOUND, {"error": "Artifact not found."})
            return
        if self.object_storage is not None:
            try:
                value = json.loads(self.object_storage.get_bytes(uri))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                self._write(HTTPStatus.NOT_FOUND, {"error": "Artifact not found."})
                return
            self._write(HTTPStatus.OK, value)
            return
        candidate = Path(uri)
        if not candidate.is_absolute():
            candidate = self.media_root / candidate
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self.media_root.resolve())
        except ValueError:
            self._write(
                HTTPStatus.FORBIDDEN, {"error": "Artifact path is outside storage."}
            )
            return
        if not resolved.is_file():
            self._write(HTTPStatus.NOT_FOUND, {"error": "Artifact not found."})
            return
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._write(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Stored artifact is not valid JSON."},
            )
            return
        self._write(HTTPStatus.OK, value)

    def _episode_json(self, episode: Episode) -> dict[str, object]:
        return {
            "id": episode.id,
            "topic": episode.topic.title,
            "subject_area": episode.topic.subject_area,
            "status": episode.status.value,
            "revision": episode.revision,
            "final_video_uri": None if self.strict_auth else episode.final_video_uri,
            "artifacts": {
                "video": (f"/media/{episode.id}" if episode.final_video_uri else None),
                "lesson": (
                    f"/episodes/{episode.id}/lesson" if episode.lesson_uri else None
                ),
                "script": (
                    f"/episodes/{episode.id}/script" if episode.script_uri else None
                ),
            },
            "created_at": episode.created_at,
        }

    @staticmethod
    def _review_json(review: Review) -> dict[str, object]:
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
    object_storage: ObjectStorage | None = None,
    strict_auth: bool = False,
    owner_id: str = "owner",
) -> ThreadingHTTPServer:
    """Create a local review server with safe binding defaults."""

    token = (
        review_token
        if review_token is not None
        else os.getenv("LATTICE_REVIEW_TOKEN", "")
    )
    if (strict_auth or host not in {"127.0.0.1", "::1", "localhost"}) and not token:
        raise ValueError("A review token is required when binding beyond localhost.")

    class ConfiguredReviewApiHandler(ReviewApiHandler):
        pass

    ConfiguredReviewApiHandler.repository = repository
    ConfiguredReviewApiHandler.review_token = token
    ConfiguredReviewApiHandler.media_root = (
        Path(media_root) if media_root is not None else None
    )
    ConfiguredReviewApiHandler.object_storage = object_storage
    ConfiguredReviewApiHandler.strict_auth = strict_auth
    ConfiguredReviewApiHandler.owner_id = owner_id
    return ThreadingHTTPServer((host, port), ConfiguredReviewApiHandler)


_REVIEW_APP = """<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lattice review</title>
<style>
body{font:16px system-ui;background:#0f172a;color:#e2e8f0;max-width:640px;margin:auto;padding:16px}
video{width:100%;border-radius:16px;background:#020617}button,textarea{font:1rem;padding:12px;border-radius:10px}
button{border:0;margin:6px 4px 6px 0}.approve{background:#86efac}.reject{background:#fca5a5}
textarea,input{width:96%;min-height:40px;padding:8px;box-sizing:border-box}.card{background:#1e293b;padding:16px;border-radius:16px;margin-top:16px}
nav{display:flex;gap:8px;overflow-x:auto;padding:8px 0}nav button{flex:0 0 auto;background:#334155;color:#e2e8f0}
nav button[aria-current="true"]{background:#fbbf24;color:#0f172a}.actions{display:flex;gap:8px}.actions button{flex:1}
</style>
<h1>Lattice review</h1><label>Bearer token (kept in memory only)
<input id="token" type="password" autocomplete="off"></label>
<p id="status">Loading queue...</p><nav id="queue"></nav><main id="card"></main>
<script>
let item,q=[],selected=0,videoUrl='';
const $=id=>document.querySelector(id);
function headers(){const token=$('#token').value.trim(); return token?{'Authorization':'Bearer '+token}:{}}
async function load(){const r=await fetch('/review-queue',{headers:headers()});
 if(!r.ok){$('#status').textContent='Unable to load queue ('+r.status+').';return}
 q=await r.json(); if(selected>=q.length)selected=0; show()}
async function show(){item=q[selected]; const nav=$('#queue'); nav.replaceChildren();
 q.forEach((entry,index)=>{const button=document.createElement('button');
 button.textContent=entry.topic+' - '+entry.revision;button.setAttribute('aria-current',String(index===selected));
 button.onclick=()=>{selected=index;show()};nav.append(button)});
 if(!item){$('#status').textContent='No videos waiting for review.';$('#card').textContent='';return}
 $('#status').textContent=item.topic+' - revision '+item.revision;
 $('#card').innerHTML='<div class="card"><video controls playsinline></video>'+
 '<p>Reject criteria (comma separated)</p><input id="criteria" placeholder="visual_clarity, pacing">'+
 '<textarea id="feedback" placeholder="Optional feedback"></textarea><br>'+
 '<label>Start <input id="start" type="number" min="0" value="0"></label>'+
 '<label>End <input id="end" type="number" min="1" value="5"></label><br>'+
 '<button type="button" onclick="useVideoTime()">Mark current video time</button><br>'+
 '<div class="actions"><button class="approve" onclick="decide(\\'approve\\')">Approve</button>'+
 '<button class="reject" onclick="decide(\\'reject\\')">Reject</button></div></div>';
 const video=$('#card video');
 const response=await fetch('/media/'+encodeURIComponent(item.id),{headers:headers()});
 if(!response.ok){$('#status').textContent='Unable to load video ('+response.status+').';return}
 if(videoUrl)URL.revokeObjectURL(videoUrl);
 videoUrl=URL.createObjectURL(await response.blob());video.src=videoUrl;
 video.load()}
function useVideoTime(){const second=Math.floor($('#card video').currentTime||0);
 $('#start').value=second;$('#end').value=second+5}
async function decide(decision){const criteria=$('#criteria').value.split(',').map(x=>x.trim()).filter(Boolean);
 const feedback=$('#feedback').value; const start=Number($('#start').value);
 const end=Number($('#end').value); const markers=criteria.length?[{start_seconds:start,end_seconds:end,criterion:criteria[0],comment:feedback}]:[];
 const r=await fetch('/episodes/'+encodeURIComponent(item.id)+'/review',{method:'POST',
 headers:Object.assign({'Content-Type':'application/json'},headers()),body:JSON.stringify({decision,reviewer_id:'owner',criteria,markers,feedback})});
 if(!r.ok){alert((await r.json()).error);return} load()} $('#token').addEventListener('change',load); load();
</script>"""
