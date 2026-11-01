"""Command-line entry points for Lattice."""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config
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
        f"({config.video_length_seconds}s, {len(config.workflow)} workflow stages)"
    )
    return 0


def review_server_main() -> int:
    """Run the local review API against a SQLite database."""

    parser = argparse.ArgumentParser(description="Run the local Lattice review API.")
    parser.add_argument("--database", default="var/lattice.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    repository = EpisodeRepository(args.database)
    server = create_review_server(repository, args.host, args.port)
    print(f"Lattice review API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        repository.close()
    return 0
