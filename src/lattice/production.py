"""Quality-gated rendering and local artifact persistence."""

from __future__ import annotations

from pathlib import Path

from .contracts import Episode, EpisodeStatus
from .media_quality import check_media
from .persistence import EpisodeRepository
from .pipeline import ProductionBundle, RenderProvider, format_production_script
from .storage import LocalObjectStorage


def render_episode_for_review(
    bundle: ProductionBundle,
    episode: Episode,
    renderer: RenderProvider,
    repository: EpisodeRepository,
    storage: LocalObjectStorage,
    expected_duration: int | None = None,
) -> Episode:
    """Render, validate, persist, and submit one processing episode for review."""

    if episode.status != EpisodeStatus.PROCESSING:
        raise ValueError("Only processing episodes can be rendered for review.")
    video = renderer.render(bundle.render_job)
    report = check_media(
        video.uri,
        expected_duration=expected_duration,
        maximum_duration=bundle.storyboard.maximum_duration_seconds,
    )
    if not report.passed:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"Rendered media failed quality checks: {issues}")

    source = Path(video.uri)
    revision_name = f"revision-{episode.revision}"
    video_key = f"videos/{episode.id}/revision-{episode.revision}.mp4"
    stored_video = storage.put_file(video_key, source)
    subtitle = source.with_suffix(".srt")
    if subtitle.is_file():
        storage.put_file(
            f"videos/{episode.id}/revision-{episode.revision}.srt",
            subtitle,
        )
    lesson = bundle.draft.research
    stored_lesson = storage.put_json(
        f"lessons/{episode.id}/{revision_name}.json",
        {
            "schema_version": 1,
            "kind": "lesson",
            "episode_id": episode.id,
            "revision": episode.revision,
            "topic": {
                "title": lesson.topic.title,
                "subject_area": lesson.topic.subject_area,
            },
            "summary": lesson.summary,
            "sections": [
                {
                    "heading": section.heading,
                    "text": section.text,
                    "visual_description": section.visual_description,
                }
                for section in bundle.draft.script.sections
            ],
            "claims": [
                {
                    "statement": claim.statement,
                    "evidence_level": claim.evidence_level,
                    "source_indices": list(claim.source_indices),
                    "uncertainty": claim.uncertainty,
                }
                for claim in lesson.claims
            ],
            "sources": [
                {
                    "title": item.title,
                    "citation": item.citation,
                    "url": item.url,
                    "source_type": item.source_type,
                }
                for item in lesson.sources
            ],
        },
    )
    script = bundle.draft.script
    stored_script = storage.put_json(
        f"scripts/{episode.id}/{revision_name}.json",
        {
            "schema_version": 1,
            "kind": "script",
            "episode_id": episode.id,
            "revision": episode.revision,
            "topic": {
                "title": script.topic.title,
                "subject_area": script.topic.subject_area,
            },
            "estimated_duration_seconds": script.estimated_duration_seconds,
            "source_claim_count": script.source_claim_count,
            "sections": [
                {
                    "heading": section.heading,
                    "text": section.text,
                    "visual_description": section.visual_description,
                }
                for section in script.sections
            ],
            "production_script": format_production_script(script, bundle.storyboard),
        },
    )
    return repository.submit_for_review(
        episode,
        str(stored_video.path),
        lesson_uri=str(stored_lesson.path),
        script_uri=str(stored_script.path),
    )
