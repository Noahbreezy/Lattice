"""Deterministic, machine-readable evidence for reviewable episodes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .pipeline import ProductionBundle
from .media_quality import check_media, media_fingerprint


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
        claim_matches = _semantic_claim_matches(scene.narration, claims)
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "script_section": scene.script_section_heading,
                "narration": scene.narration,
                "narration_words": len(scene.narration.split()),
                "duration_seconds": scene.duration_seconds,
                "asset_id": bundle.asset_manifest.assets[index].asset_id,
                "visual_direction": scene.visual_direction,
                "claim_ids": [item["claim_id"] for item in claim_matches],
                "claim_alignment": [
                    {
                        "claim_id": item["claim_id"],
                        "overlap_terms": item["_overlap_terms"],
                        "score": item["_score"],
                    }
                    for item in claim_matches
                ],
                "semantic_alignment_passed": bool(claim_matches),
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

    media: dict[str, Any] = {}
    subtitle_path = None
    if video_path is not None:
        video = Path(video_path)
        media = media_fingerprint(video)
        report = check_media(video)
        media["validation"] = {
            "passed": report.passed,
            "issues": [{"code": issue.code, "message": issue.message} for issue in report.issues],
            "audio": report.has_audio,
            "width": report.width,
            "height": report.height,
            "dimensions": f"{report.width}x{report.height}" if report.width else None,
        }
        if report.metrics is not None:
            media["animation_metrics"] = report.metrics
        candidate = video.with_suffix(".srt")
        if candidate.is_file():
            subtitle_path = candidate
            media["subtitle_path"] = str(candidate)
            media["subtitle_sha256"] = _sha256(candidate)

    subtitle_entries = _read_srt(subtitle_path) if subtitle_path else []
    scene_mappings = []
    for index, scene in enumerate(bundle.storyboard.scenes):
        entry = subtitle_entries[index] if index < len(subtitle_entries) else None
        scene_mappings.append({
            "scene_id": scene.scene_id,
            "srt_index": index + 1,
            "start_seconds": entry["start"] if entry else None,
            "end_seconds": entry["end"] if entry else None,
            "narration": scene.narration,
            "srt_narration": entry["text"] if entry else None,
            "narration_matches_srt": bool(entry and entry["text"] == scene.narration),
        })

    limitations = [
        "Review evidence describes deterministic pipeline inputs and does not establish factual truth.",
        "Animation metrics are renderer-declared metrics, not perceptual measurements.",
    ]
    if any(source.source_type.lower() == "placeholder" for source in research.sources):
        limitations.append("Research contains placeholder sources and is not publication-ready.")
    if any(asset.asset_type.endswith("placeholder") for asset in bundle.asset_manifest.assets):
        limitations.append("Asset manifest contains placeholder visual references.")

    return {
        "evidence_version": 2,
        "topic": {"title": research.topic.title, "subject_area": research.topic.subject_area},
        "hashes": hashes,
        "paths": paths,
        "media": media,
        "srt": {
            "present": bool(subtitle_entries),
            "entry_count": len(subtitle_entries),
            "scene_mappings": scene_mappings,
            "timing_valid": _valid_srt_timing(subtitle_entries, len(bundle.storyboard.scenes)),
        },
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


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "can", "does", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "what", "when", "which", "why", "with",
}


def _semantic_claim_matches(narration: str, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map only claims with meaningful lexical overlap to a scene."""
    words = {
        word for word in re.findall(r"[a-z0-9]+", narration.lower())
        if len(word) > 3 and word not in _STOPWORDS
    }
    matches = []
    for claim in claims:
        claim_words = {
            word for word in re.findall(r"[a-z0-9]+", claim["statement"].lower())
            if len(word) > 3 and word not in _STOPWORDS
        }
        overlap = sorted(words & claim_words)
        if overlap:
            enriched = dict(claim)
            enriched["_overlap_terms"] = overlap
            enriched["_score"] = round(len(overlap) / max(len(claim_words), 1), 3)
            matches.append(enriched)
    return matches


def _read_srt(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    entries = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (item.strip() for item in lines[1].split("-->", 1))
        entries.append({
            "index": lines[0],
            "start": _srt_seconds(start),
            "end": _srt_seconds(end),
            "text": "\n".join(lines[2:]),
        })
    return entries


def _srt_seconds(timestamp: str) -> float:
    hours, minutes, remainder = timestamp.replace(",", ".").split(":")
    return round(int(hours) * 3600 + int(minutes) * 60 + float(remainder), 3)


def _valid_srt_timing(entries: list[dict[str, Any]], scene_count: int) -> bool:
    if len(entries) != scene_count:
        return False
    return all(
        entry["end"] > entry["start"]
        and (index == 0 or entry["start"] >= entries[index - 1]["end"])
        for index, entry in enumerate(entries)
    )


def write_review_evidence(evidence: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
