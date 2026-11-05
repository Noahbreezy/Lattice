"""Quality-gated rendering and local artifact persistence."""

from __future__ import annotations

from pathlib import Path

from .contracts import Episode, EpisodeStatus
from .media_quality import check_media
from .persistence import EpisodeRepository
from .pipeline import ProductionBundle, RenderProvider
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
    report = check_media(video.uri, expected_duration=expected_duration)
    if not report.passed:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"Rendered media failed quality checks: {issues}")

    source = Path(video.uri)
    video_key = f"videos/{episode.id}/revision-{episode.revision}.mp4"
    stored_video = storage.put_file(video_key, source)
    subtitle = source.with_suffix(".srt")
    if subtitle.is_file():
        storage.put_file(
            f"videos/{episode.id}/revision-{episode.revision}.srt",
            subtitle,
        )
    return repository.submit_for_review(episode, str(stored_video.path))
