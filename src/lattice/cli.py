"""Command-line entry points for Lattice."""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config


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
