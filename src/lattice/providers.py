"""Optional capability adapters selected by project configuration."""

from __future__ import annotations

from importlib.metadata import entry_points


def provider_factory(capability: str, name: str):
    """Load an installed provider factory, or return None if unavailable.

    Extensions register an entry point in ``lattice.<capability>``. Lesson,
    narration, and visual factories receive ``(config, tool)``. Editor
    factories receive ``(config, tool, output_dir, tts, visual)``.
    """

    matches = entry_points(group=f"lattice.{capability}")
    for entry in matches:
        if entry.name == name:
            return entry.load()
    return None
