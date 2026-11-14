"""Durable local production of one configured episode revision."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from .config import ProjectConfig
from .contracts import Episode, EpisodeStatus, ReviewDecision
from .evidence import build_review_evidence, write_review_evidence
from .history import LessonHistory
from .persistence import EpisodeRepository, Job
from .pipeline import (
    RenderProvider,
    assemble_production_bundle,
    format_production_script,
    generate_episode_draft,
    select_topic,
)
from .production import store_rendered_episode, validate_rendered_video
from .providers import provider_factory
from .quality import require_script_quality
from .renderer import FfmpegRenderer
from .research import AILessonProvider, create_configured_research_provider
from .storage import LocalObjectStorage, ObjectStorage
from .tts import PiperTts, WindowsSpeechTts
from .visuals import IllustratedVisualProvider
from .worker import LocalWorker

_PRODUCTION_STAGES = (
    "select topic",
    "generate structured lesson and script",
    "run lesson and script quality checks",
    "create storyboard and local visual assets",
    "render and caption video",
    "validate rendered media",
    "store private review artifacts",
    "human quality review and revision",
)


def _validate_local_capabilities(config: ProjectConfig, offline: bool) -> None:
    """Fail closed when a requested capability has no local adapter."""

    if config.workflow != _PRODUCTION_STAGES:
        raise ValueError(
            "The local production runner requires the configured workflow stages "
            "in their execution order."
        )
    tools = {str(item["name"]).strip().lower(): item for item in config.ai_tools}
    if len(tools) != len(config.ai_tools):
        raise ValueError("production.ai_tools contains duplicate capability names.")
    for capability in ("editor", "narration"):
        if capability not in tools:
            raise ValueError(f"A {capability} capability is required for production.")
    editor = tools.get("editor", {})
    editor_provider = str(editor.get("provider") or "ffmpeg").lower()
    if (
        editor_provider not in {"ffmpeg", "local"}
        and provider_factory("editor", editor_provider) is None
    ):
        raise ValueError(f"Unsupported editor provider: {editor_provider}")
    visual = tools.get("video generator", {})
    visual_provider = str(visual.get("provider") or "local").lower()
    if (
        visual.get("required")
        and visual_provider not in {"local", "illustrated"}
        and provider_factory("visual", visual_provider) is None
    ):
        raise ValueError(f"Unsupported required video generator: {visual_provider}")
    if not offline and "script model" not in tools:
        raise ValueError("A script model capability is required for production.")
    if not offline:
        create_configured_research_provider(config)
    narration = tools.get("narration", {})
    narration_provider = str(narration.get("provider") or "windows-sapi").lower()
    if (
        narration_provider not in {"windows-sapi", "piper"}
        and provider_factory("narration", narration_provider) is None
    ):
        raise ValueError(f"Unsupported narration provider: {narration_provider}")
    if narration_provider == "piper" and not narration.get("model"):
        raise ValueError("A Piper narration provider requires a model path.")


def _configured_renderer(config: ProjectConfig, output: Path) -> RenderProvider:
    tools = {str(item["name"]).strip().lower(): item for item in config.ai_tools}
    narration = tools.get("narration", {})
    narration_name = str(narration.get("provider") or "windows-sapi").lower()
    if narration_name == "piper":
        tts = PiperTts(str(narration["model"]))
    elif narration_name == "windows-sapi":
        tts = WindowsSpeechTts(
            voice=str(narration.get("voice") or ""),
            rate=int(narration.get("rate") or 0),
        )
    else:
        narration_factory = provider_factory("narration", narration_name)
        if narration_factory is None:
            raise ValueError(f"Unsupported narration provider: {narration_name}")
        tts = narration_factory(config, narration)
    visual = tools.get("video generator", {})
    visual_name = str(visual.get("provider") or "local").lower()
    visual_factory = provider_factory("visual", visual_name)
    visual_adapter = (
        visual_factory(config, visual)
        if visual_factory is not None
        else IllustratedVisualProvider()
    )
    editor = tools.get("editor", {})
    editor_name = str(editor.get("provider") or "ffmpeg").lower()
    editor_factory = provider_factory("editor", editor_name)
    if editor_factory is not None:
        return editor_factory(config, editor, output, tts, visual_adapter)
    return FfmpegRenderer(output, tts_provider=tts, visual_provider=visual_adapter)


def run_next_episode(
    config: ProjectConfig,
    repository: EpisodeRepository,
    history: LessonHistory,
    output: str | Path,
    *,
    offline: bool = False,
    lesson_provider: AILessonProvider | None = None,
    renderer_factory: Callable[[Path], RenderProvider] | None = None,
    storage: ObjectStorage | None = None,
) -> Episode:
    """Queue and produce one episode, preferring rejected revisions."""

    _validate_local_capabilities(config, offline)
    output = Path(output)
    storage = storage or LocalObjectStorage(output / "review-media")
    queue = repository.list_queue()
    if queue:
        episode = queue[0]
    else:
        topic = select_topic(config, history)
        episode_id = (
            "episode-"
            + hashlib.sha256(f"{config.config_hash}:{topic.key}".encode()).hexdigest()[
                :16
            ]
        )
        episode = Episode(episode_id, topic, EpisodeStatus.QUEUED, 1)
        repository.save(episode)
        repository.create_revision(episode_id, 1)

    job = repository.enqueue_job(
        f"produce:{episode.id}:revision-{episode.revision}",
        "produce",
        f"{episode.id}:revision-{episode.revision}",
        json.dumps({"episode_id": episode.id, "revision": episode.revision}),
    )
    if job.status == "failed":
        raise RuntimeError(f"Production job failed: {job.error}")

    def produce(work: Job) -> None:
        payload = json.loads(work.payload)
        current = repository.get(payload["episode_id"])
        if current is None or current.revision != payload["revision"]:
            raise ValueError("Production job no longer matches the queued revision.")
        if current.status == EpisodeStatus.AWAITING_REVIEW:
            return  # The prior attempt submitted before its job was acknowledged.
        processing = (
            current
            if current.status == EpisodeStatus.PROCESSING
            else repository.claim_episode(current.id)
        )
        try:
            reviews = repository.reviews_for(processing.id)
            rejection = (
                next(
                    (
                        item
                        for item in reversed(reviews)
                        if item.decision == ReviewDecision.REJECT
                    ),
                    None,
                )
                if processing.revision > 1
                else None
            )
            if processing.revision > 1 and rejection is None:
                raise ValueError("Rejected revision is missing its saved review.")
            revision_dir = (
                output / "episodes" / processing.id / f"revision-{processing.revision}"
            )
            artifact_path = revision_dir / "bundle.json"
            script_path = revision_dir / "production.script.md"
            manifest_path = revision_dir / "manifest.json"
            draft = bundle = renderer = video = submitted = None
            for stage in config.workflow:
                if stage == "select topic":
                    continue  # The queue claim above fixes the topic for this revision.
                if stage == "generate structured lesson and script":
                    draft = generate_episode_draft(
                        config,
                        history,
                        lesson_provider=lesson_provider,
                        offline=offline,
                        topic=processing.topic,
                        review=rejection,
                    )
                elif stage == "run lesson and script quality checks":
                    if draft is None:
                        raise RuntimeError("Lesson generation must precede quality checks.")
                    if not offline:
                        require_script_quality(config, draft.research, draft.script)
                elif stage == "create storyboard and local visual assets":
                    if draft is None:
                        raise RuntimeError("Lesson generation must precede storyboard creation.")
                    bundle = assemble_production_bundle(config, draft, review=rejection)
                    revision_dir.mkdir(parents=True, exist_ok=True)
                    artifact_path.write_text(
                        json.dumps(
                            dataclasses.asdict(bundle),
                            indent=2,
                            sort_keys=True,
                            default=str,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    script_path.write_text(
                        format_production_script(
                            bundle.draft.script, bundle.storyboard
                        ),
                        encoding="utf-8",
                    )
                elif stage == "render and caption video":
                    if bundle is None:
                        raise RuntimeError("Storyboard creation must precede rendering.")
                    renderer = (
                        renderer_factory(revision_dir / "rendered")
                        if renderer_factory is not None
                        else _configured_renderer(config, revision_dir / "rendered")
                    )
                    video = renderer.render(bundle.render_job)
                elif stage == "validate rendered media":
                    if bundle is None or renderer is None or video is None:
                        raise RuntimeError("Rendering must precede media validation.")
                    materialized = getattr(renderer, "last_job", None)
                    expected_duration = (
                        sum(
                            scene.duration_seconds
                            for scene in materialized.storyboard.scenes
                        )
                        if materialized is not None
                        else None
                    )
                    validate_rendered_video(bundle, video.uri, expected_duration)
                elif stage == "store private review artifacts":
                    if bundle is None or renderer is None or video is None:
                        raise RuntimeError("Rendering must precede artifact storage.")
                    materialized = getattr(renderer, "last_job", None)
                    manifest = (
                        materialized.asset_manifest
                        if materialized is not None
                        else bundle.asset_manifest
                    )
                    manifest_path.write_text(
                        json.dumps(
                            dataclasses.asdict(manifest),
                            indent=2,
                            sort_keys=True,
                            default=str,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    artifact_prefix = (
                        f"episodes/{processing.id}/revision-{processing.revision}"
                    )
                    for name, path in (
                        ("bundle.json", artifact_path),
                        ("production.script.md", script_path),
                        ("manifest.json", manifest_path),
                    ):
                        storage.put_file(f"{artifact_prefix}/{name}", path)
                    if isinstance(storage, LocalObjectStorage):
                        storage.put_file(
                            f"videos/{processing.id}/revision-{processing.revision}.manifest.json",
                            manifest_path,
                        )
                    evidence_path = revision_dir / "evidence.json"
                    write_review_evidence(
                        build_review_evidence(
                            bundle,
                            artifact_path=artifact_path,
                            manifest_path=manifest_path,
                            video_path=video.uri,
                        ),
                        evidence_path,
                    )
                    storage.put_file(f"{artifact_prefix}/evidence.json", evidence_path)
                    submitted = store_rendered_episode(
                        bundle,
                        processing,
                        video.uri,
                        repository,
                        storage,
                    )
                elif (
                    stage == "human quality review and revision"
                    and (submitted is None or submitted.status != EpisodeStatus.AWAITING_REVIEW)
                ):
                    raise RuntimeError("Production did not enter the review queue.")
        except Exception:
            # A worker retry must be able to claim the same revision again.
            current = repository.get(processing.id)
            if current is not None and current.status == EpisodeStatus.PROCESSING:
                repository.save(
                    Episode(
                        current.id,
                        current.topic,
                        EpisodeStatus.REJECTED
                        if current.revision > 1
                        else EpisodeStatus.QUEUED,
                        current.revision,
                        current.final_video_uri,
                        current.created_at,
                        current.lesson_uri,
                        current.script_uri,
                    ),
                    queue_priority=-current.revision,
                )
            raise

    finished = LocalWorker(repository, {"produce": produce}).run_once("produce", job.id)
    if finished is None or finished.id != job.id:
        raise RuntimeError("Production job was not available to the worker.")
    if finished.status != "succeeded":
        raise RuntimeError(
            f"Production job failed (attempt {finished.attempts}): {finished.error}"
        )
    result = repository.get(episode.id)
    if result is None or result.status != EpisodeStatus.AWAITING_REVIEW:
        raise RuntimeError(
            "Production completed without submitting the episode for review."
        )
    return result


configured_renderer = _configured_renderer
validate_local_capabilities = _validate_local_capabilities
