"""Command-line entry points for Lattice."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .history import LessonHistory
from .local_api import create_review_server
from .persistence import EpisodeRepository


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
        f"(under 180s; {config.max_video_length_seconds}s maximum, "
        f"{len(config.workflow)} workflow stages)"
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
        pass
    finally:
        server.server_close()
        repository.close()
    return 0


def run_local_main() -> int:
    """Produce one configured episode or queued rejected revision."""

    from .runner import run_next_episode

    parser = argparse.ArgumentParser(
        description="Produce one local episode for review."
    )
    parser.add_argument("config", help="Path to a JSON project configuration.")
    parser.add_argument("--database", default="var/lattice.sqlite")
    parser.add_argument("--output", default="var/lattice-artifacts")
    parser.add_argument("--history", default="var/lesson-history.json")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the deterministic lesson fixture instead of the configured provider.",
    )
    args = parser.parse_args()
    repository = None
    try:
        config = load_config(args.config)
        database_path = Path(args.database)
        if str(database_path) != ":memory:":
            database_path.parent.mkdir(parents=True, exist_ok=True)
        repository = EpisodeRepository(args.database)
        episode = run_next_episode(
            config,
            repository,
            LessonHistory(args.history),
            args.output,
            offline=args.offline,
        )
        print(f"Episode: {episode.id}")
        print(f"Revision: {episode.revision}")
        print(f"Video: {episode.final_video_uri}")
        print(f"Queue status: {episode.status.value}")
        return 0
    except (ConfigError, OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"Local run failed: {error}", file=sys.stderr)
        return 1
    finally:
        if repository is not None:
            repository.close()
