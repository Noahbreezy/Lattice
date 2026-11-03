"""Deterministic, machine-readable evidence for reviewable episodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .pipeline import ProductionBundle


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def build_review_evidence(
    bundle: ProductionBundle,
    *,
    artifact_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    video_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build stable review evidence without depending on a media vendor."""

    research = bundle.draft.research
    script = bundle.draft.script
    claims = [
        {
            "claim_id": f"claim-{index + 1}",
            "statement": claim.statement,
            "source_indices": list(claim.source_indices),
            "source_ids": [f"source-{source + 1}" for source in claim.source_indices],
            "evidence_level": claim.evidence_level,
            "uncertainty": claim.uncertainty,
        }
        for index, claim in enumerate(research.claims)
    ]
    scenes = []
    for index, scene in enumerate(bundle.storyboard.scenes):
        section = next(
            (item for item in script.sections if item.heading == scene.script_section_heading),
            None,
        )
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "script_section": scene.script_section_heading,
                "narration": scene.narration,
                "narration_words": len(scene.narration.split()),
                "duration_seconds": scene.duration_seconds,
                "asset_id": bundle.asset_manifest.assets[index].asset_id,
                "visual_direction": scene.visual_direction,
                "claim_ids": [item["claim_id"] for item in claims],
                "script_text_hash": hashlib.sha256(
                    (section.text if section else scene.narration).encode("utf-8")
                ).hexdigest(),
                "animation_metrics": {
                    "motion_profile": "restrained",
                    "animated_scene": True,
                    "visual_layers": 2,
                },
            }
        )

    paths = {}
    hashes = {}
    for name, value in (
        ("artifact", artifact_path),
        ("manifest", manifest_path),
        ("video", video_path),
    ):
        if value is not None:
            path = Path(value)
            paths[name] = str(path)
            hashes[name] = _sha256(path)

    limitations = [
        "Review evidence describes deterministic pipeline inputs and does not establish factual truth.",
        "Animation metrics are renderer-declared metrics, not perceptual measurements.",
    ]
    if any(source.source_type.lower() == "placeholder" for source in research.sources):
        limitations.append("Research contains placeholder sources and is not publication-ready.")
    if any(asset.asset_type.endswith("placeholder") for asset in bundle.asset_manifest.assets):
        limitations.append("Asset manifest contains placeholder visual references.")

    return {
        "evidence_version": 1,
        "topic": {"title": research.topic.title, "subject_area": research.topic.subject_area},
        "hashes": hashes,
        "paths": paths,
        "provenance": {
            "research": f"research:{research.topic.key}:v1",
            "script": script.provenance.artifact_id if script.provenance else "",
            "storyboard": bundle.storyboard.provenance.artifact_id
            if bundle.storyboard.provenance
            else "",
            "asset_manifest": bundle.asset_manifest.provenance.artifact_id
            if bundle.asset_manifest.provenance
            else "",
        },
        "sources": [
            {
                "source_id": f"source-{index + 1}",
                "title": source.title,
                "citation": source.citation,
                "url": source.url,
                "source_type": source.source_type,
            }
            for index, source in enumerate(research.sources)
        ],
        "claims": claims,
        "scenes": scenes,
        "timing": {
            "script_estimated_seconds": script.estimated_duration_seconds,
            "storyboard_seconds": sum(scene.duration_seconds for scene in bundle.storyboard.scenes),
            "scene_count": len(bundle.storyboard.scenes),
        },
        "limitations": limitations,
    }


def write_review_evidence(evidence: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
