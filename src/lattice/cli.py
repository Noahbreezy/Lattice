"""Command-line entry points for Lattice."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import sqlite3
import sys
from enum import Enum
from pathlib import Path

from .config import ConfigError, load_config
from .evidence import build_review_evidence, write_review_evidence
from .contracts import Episode, EpisodeStatus
from .history import LessonHistory
from .local_api import create_review_server
from .pipeline import build_production_bundle
from .persistence import EpisodeRepository
from .production import render_episode_for_review
from .renderer import FfmpegRenderer
from .storage import LocalObjectStorage


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Lattice project config.")
    parser.add_argument("config", help="Path to a JSON project configuration.")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return 1

    print(
        f"Valid configuration: {config.name} "
        f"({config.video_length_seconds}s, {len(config.workflow)} workflow stages)"
    )
    return 0


def review_server_main() -> int:
    """Run the local review API against a SQLite database."""

    parser = argparse.ArgumentParser(description="Run the local Lattice review API.")
    parser.add_argument("--database", default="var/lattice.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--media-root",
        default="var/lattice-artifacts/review-media",
        help="Directory containing generated review videos.",
    )
    args = parser.parse_args()
    database_path = Path(args.database)
    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)
    repository = EpisodeRepository(args.database)
    server = create_review_server(
        repository,
        args.host,
        args.port,
        media_root=args.media_root,
    )
    print(f"Lattice review API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


def run_local_main() -> int:
    """Build one deterministic offline artifact and place it in review."""

    parser = argparse.ArgumentParser(
        description="Build a local offline episode and submit it for review."
    )
    parser.add_argument("config", help="Path to a JSON project configuration.")
    parser.add_argument("--database", default="var/lattice.sqlite")
    parser.add_argument("--output", default="var/lattice-artifacts")
    parser.add_argument("--history", default="var/lesson-history.json")
    args = parser.parse_args()

    repository: EpisodeRepository | None = None
    try:
        config = load_config(args.config)
        history = LessonHistory(args.history)
        bundle = build_production_bundle(config, history, offline=True)
        topic_key = bundle.draft.topic.key
        episode_id = "episode-" + hashlib.sha256(
            f"{config.config_hash}:{topic_key}".encode("utf-8")
        ).hexdigest()[:16]
        artifact_dir = Path(args.output)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        payload = _stable_value(
            {
                "config_hash": config.config_hash,
                "episode_id": episode_id,
                "topic": bundle.draft.topic,
                "research": bundle.draft.research,
                "script": bundle.draft.script,
                "storyboard": bundle.storyboard,
                "asset_manifest": bundle.asset_manifest,
                "render_job": bundle.render_job,
            }
        )
        artifact_path = artifact_dir / f"{episode_id}.json"
        manifest_path = artifact_dir / f"{episode_id}.manifest.json"
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        artifact_path.write_text(serialized, encoding="utf-8")
        manifest_path.write_text(
            json.dumps(_stable_value(bundle.asset_manifest), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        evidence_path = artifact_dir / f"{episode_id}.evidence.json"
        write_review_evidence(
            build_review_evidence(
                bundle,
                artifact_path=artifact_path,
                manifest_path=manifest_path,
            ),
            evidence_path,
        )

        repository = EpisodeRepository(args.database)
        processing = Episode(
            episode_id, bundle.draft.topic, EpisodeStatus.PROCESSING, 1
        )
        repository.save(processing)
        rendered_dir = artifact_dir / "rendered"
        renderer = FfmpegRenderer(rendered_dir)
        awaiting = render_episode_for_review(
            bundle,
            processing,
            renderer,
            repository,
            LocalObjectStorage(artifact_dir / "review-media"),
            expected_duration=config.video_length_seconds,
        )
        # Persist the materialized explanatory SVGs, not the pre-render
        # placeholder manifest, for local inspection and review tooling.
        if renderer.last_job is not None:
            bundle_manifest = renderer.last_job.asset_manifest
            payload["asset_manifest"] = _stable_value(bundle_manifest)
            payload["render_job"] = _stable_value(renderer.last_job)
            artifact_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(_stable_value(bundle_manifest), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        # Keep the manifest adjacent to the reviewable video for local consumers.
        shutil.copyfile(manifest_path, Path(awaiting.final_video_uri).with_suffix(".manifest.json"))
        rendered_evidence = Path(awaiting.final_video_uri).with_suffix(".evidence.json")
        evidence = build_review_evidence(
            bundle,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            video_path=awaiting.final_video_uri,
        )
        write_review_evidence(evidence, rendered_evidence)
        print(f"Episode: {awaiting.id}")
        print(f"Artifact: {artifact_path}")
        print(f"Manifest: {manifest_path}")
        print(f"Evidence: {evidence_path}")
        print(f"Queue status: {awaiting.status.value}")
        return 0
    except (ConfigError, OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"Local run failed: {error}", file=sys.stderr)
        return 1
    finally:
        if repository is not None:
            repository.close()


def _stable_value(value: object) -> object:
    """Convert domain dataclasses to JSON while omitting volatile timestamps."""

    if dataclasses.is_dataclass(value):
        return {
            field.name: _stable_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.name not in {"created_at", "updated_at"}
        }
    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item in value.items()
            if key not in {"created_at", "updated_at"}
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_stable_value(item) for item in value]
    return value
