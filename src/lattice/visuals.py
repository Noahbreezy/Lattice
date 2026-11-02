"""Provider-neutral illustrated asset generation."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Protocol

from .contracts import AssetReference, StoryboardScene


class VisualProvider(Protocol):
    def create(self, scene: StoryboardScene, output_dir: str | Path) -> AssetReference:
        """Create a visual asset for one scene."""


class IllustratedVisualProvider:
    """Free deterministic SVG provider for concept diagrams and title cards."""

    def create(self, scene: StoryboardScene, output_dir: str | Path) -> AssetReference:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{scene.scene_id}.svg"
        heading = html.escape(scene.script_section_heading)
        direction = html.escape(scene.visual_direction)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920">
<rect width="100%" height="100%" fill="#172554"/>
<circle cx="170" cy="250" r="95" fill="#fbbf24"/>
<circle cx="910" cy="520" r="140" fill="#67e8f9" opacity=".8"/>
<path d="M140 1230 C340 980 700 1500 940 1120" stroke="#fbbf24" stroke-width="24" fill="none"/>
<rect x="100" y="1420" width="880" height="290" rx="32" fill="#0f172a" opacity=".82"/>
<text x="120" y="1550" fill="#f8fafc" font-size="54" font-family="sans-serif">{heading}</text>
<text x="120" y="1635" fill="#cbd5e1" font-size="26" font-family="sans-serif">{direction[:90]}</text>
</svg>"""
        path.write_text(svg, encoding="utf-8")
        return AssetReference(scene.scene_id + "-illustration", "svg-illustration", str(path))
