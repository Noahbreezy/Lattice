"""Provider-neutral illustrated asset generation."""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Protocol

from .contracts import AssetReference, StoryboardScene


class VisualProvider(Protocol):
    def create(self, scene: StoryboardScene, output_dir: str | Path) -> AssetReference:
        """Create a visual asset for one scene."""
        ...


def validate_svg(path: str | Path) -> None:
    """Reject malformed or unreadable SVGs before they enter a render job."""

    asset = Path(path)
    if not asset.is_file() or asset.stat().st_size == 0:
        raise ValueError(f"SVG asset is missing or empty: {asset}")
    try:
        root = ET.fromstring(asset.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ET.ParseError) as exc:
        raise ValueError(f"SVG asset is not valid XML: {asset}") from exc
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError(f"SVG asset root element must be <svg>: {asset}")
    if root.attrib.get("width") != "1080" or root.attrib.get("height") != "1920":
        raise ValueError(f"SVG asset must be 1080x1920: {asset}")
    if not any(
        element.tag.rsplit("}", 1)[-1] == "text" and (element.text or "").strip()
        for element in root.iter()
    ):
        raise ValueError(f"SVG asset must contain readable text: {asset}")
    if any(
        element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject"}
        for element in root.iter()
    ):
        raise ValueError(f"SVG asset contains unsupported executable content: {asset}")


class IllustratedVisualProvider:
    """Free deterministic SVG provider for concept diagrams and title cards."""

    def create(self, scene: StoryboardScene, output_dir: str | Path) -> AssetReference:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{scene.scene_id}.svg"
        heading = html.escape(scene.script_section_heading)
        direction = html.escape(scene.visual_direction)
        topic = html.escape(_topic_from_direction(scene.visual_direction))
        cause, mechanism, outcome = _explanation_labels(scene.narration)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920">
<rect width="100%" height="100%" fill="#172554"/>
<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6"
 orient="auto"><path d="M0,0 L12,6 L0,12 z" fill="#fbbf24"/></marker></defs>
<text x="90" y="130" fill="#f8fafc" font-size="42" font-family="sans-serif">HOW IT WORKS</text>
<text x="90" y="200" fill="#cbd5e1" font-size="30" font-family="sans-serif">{topic}</text>
<rect x="80" y="330" width="920" height="240" rx="28" fill="#1e3a8a"/>
<rect x="80" y="800" width="920" height="240" rx="28" fill="#164e63"/>
<rect x="80" y="1270" width="920" height="240" rx="28" fill="#365314"/>
<text x="125" y="420" fill="#fbbf24" font-size="30" font-family="sans-serif">CAUSE</text>
<text x="125" y="485" fill="#f8fafc" font-size="42" font-family="sans-serif">{cause}</text>
<text x="125" y="890" fill="#67e8f9" font-size="30" font-family="sans-serif">MECHANISM</text>
<text x="125" y="955" fill="#f8fafc" font-size="42" font-family="sans-serif">{mechanism}</text>
<text x="125" y="1360" fill="#bef264" font-size="30" font-family="sans-serif">OUTCOME</text>
<text x="125" y="1425" fill="#f8fafc" font-size="42" font-family="sans-serif">{outcome}</text>
<path d="M540 575 L540 790" stroke="#fbbf24" stroke-width="18" marker-end="url(#arrow)"/>
<path d="M540 1045 L540 1260" stroke="#fbbf24" stroke-width="18" marker-end="url(#arrow)"/>
<rect x="100" y="1580" width="880" height="250" rx="32" fill="#0f172a" opacity=".82"/>
<text x="120" y="1680" fill="#f8fafc" font-size="46" font-family="sans-serif">{heading}</text>
<text x="120" y="1740" fill="#cbd5e1" font-size="24" font-family="sans-serif">{direction[:110]}</text>
</svg>"""
        path.write_text(svg, encoding="utf-8")
        validate_svg(path)
        return AssetReference(
            scene.scene_id + "-illustration", "svg-illustration", str(path)
        )


def _topic_from_direction(direction: str) -> str:
    marker = "for '"
    if marker in direction:
        return direction.split(marker, 1)[1].split("'", 1)[0]
    return "Concept overview"


def _explanation_labels(narration: str) -> tuple[str, str, str]:
    """Turn the actual spoken explanation into three readable diagram nodes."""

    words = narration.split()
    if not words:
        raise ValueError("A visual requires non-empty scene narration.")
    chunks = [words[: max(1, len(words) // 3)]]
    chunks.append(words[len(chunks[0]) : len(words) * 2 // 3])
    chunks.append(words[len(chunks[0]) + len(chunks[1]) :])
    labels = [" ".join(chunk).strip() or "See the explanation" for chunk in chunks]
    return tuple(html.escape(label[:52]) for label in labels)  # type: ignore[return-value]
