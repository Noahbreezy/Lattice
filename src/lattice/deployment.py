"""Environment-configured server and production worker entry points."""

from __future__ import annotations

import argparse
import os
import sys
import time

from .config import load_config
from .history import LessonHistory
from .local_api import create_review_server
from .postgres import PostgresEpisodeRepository
from .runner import run_next_episode
from .storage import S3ObjectStorage


def _resources():
    dsn = os.environ.get("LATTICE_DATABASE_URL", "")
    bucket = os.environ.get("LATTICE_STORAGE_BUCKET", "")
    if not dsn or not bucket:
        raise ValueError(
            "LATTICE_DATABASE_URL and LATTICE_STORAGE_BUCKET are required."
        )
    repository = PostgresEpisodeRepository(dsn)
    storage = S3ObjectStorage(
        bucket,
        prefix=os.environ.get("LATTICE_STORAGE_PREFIX", ""),
        endpoint_url=os.environ.get("LATTICE_S3_ENDPOINT_URL") or None,
    )
    return repository, storage


def server_main() -> int:
    """Serve the mobile review queue over a TLS-terminating reverse proxy."""

    parser = argparse.ArgumentParser(
        description="Run the authenticated Lattice review server."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    token = os.environ.get("LATTICE_REVIEW_TOKEN", "")
    if not token:
        print("LATTICE_REVIEW_TOKEN is required.", file=sys.stderr)
        return 1
    repository, storage = _resources()
    try:
        server = create_review_server(
            repository,
            host=args.host,
            port=args.port,
            review_token=token,
            object_storage=storage,
            strict_auth=True,
            owner_id=os.environ.get("LATTICE_REVIEWER_ID", "owner"),
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        repository.close()
    return 0


def worker_main() -> int:
    """Process configured topics and rejected revisions until stopped."""

    parser = argparse.ArgumentParser(description="Run the Lattice production worker.")
    parser.add_argument("config")
    parser.add_argument("--output", default="var/lattice-artifacts")
    parser.add_argument("--history", default="var/lesson-history.json")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be positive")
    config = load_config(args.config)
    repository, storage = _resources()
    try:
        history = LessonHistory(args.history)
        while True:
            try:
                episode = run_next_episode(
                    config,
                    repository,
                    history,
                    args.output,
                    storage=storage,
                )
                print(
                    f"Submitted {episode.id} revision {episode.revision} for review.",
                    flush=True,
                )
            except ValueError as exc:
                if "No unused topic seeds remain" not in str(exc):
                    raise
                if args.once:
                    return 0
            if args.once:
                return 0
            time.sleep(args.interval)
    finally:
        repository.close()
