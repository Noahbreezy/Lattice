"""Local, provider-independent content pipeline for development and tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import ProjectConfig
from .contracts import (
    ApprovalState,
    ArtifactProvenance,
    AssetManifest,
    AssetReference,
    Claim,
    PublishedVideo,
    RenderJob,
    RenderJobStatus,
    ResearchPacket,
    Script,
    ScriptSection,
    Source,
    Storyboard,
    StoryboardScene,
    Topic,
    now_utc,
)
from .history import LessonHistory


@dataclass(frozen=True)
class EpisodeDraft:
    topic: Topic
    research: ResearchPacket
    script: Script


class RenderProvider(Protocol):
    """Provider-neutral rendering capability used by production adapters."""

    def render(self, job: RenderJob) -> PublishedVideo:
        """Render a job and return an unapproved private video artifact."""


def select_topic(config: ProjectConfig, history: LessonHistory) -> Topic:
    """Atomically reserve the first configured topic not in lesson history."""

    topics = (Topic(seed["title"], seed["subject_area"]) for seed in config.topic_seeds)
    return history.reserve_next(topics)


def build_research_packet(topic: Topic) -> ResearchPacket:
    """Build a clearly provisional packet for local development.

    Real research providers will replace this deterministic fixture. Keeping the
    source and claim relationship explicit prevents unsupported scripts.
    """

    source = Source(
        title=f"Research starting point: {topic.title}",
        citation="Local research placeholder; replace before publication.",
        url="https://example.invalid/research-required",
        source_type="placeholder",
    )
    claim = Claim(
        statement=f"{topic.title} is worth investigating because it explains part of how systems work.",
        evidence_level="unverified",
        source_indices=(0,),
        uncertainty="This local packet is not publication-ready.",
    )
    return ResearchPacket(
        topic=topic,
        summary=f"Research is required to explain {topic.title} accurately.",
        sources=(source,),
        claims=(claim,),
        created_at=now_utc(),
    )


def build_script(
    config: ProjectConfig, research: ResearchPacket, words_per_minute: int = 150
) -> Script:
    if words_per_minute < 60:
        raise ValueError("words_per_minute must be at least 60.")
    sections = tuple(
        ScriptSection(
            heading=heading,
            text=_section_text(heading, research),
        )
        for heading in config.required_sections
    )
    word_count = sum(len(section.text.split()) for section in sections)
    estimated_duration = max(1, round(word_count / words_per_minute * 60))
    return Script(
        topic=research.topic,
        sections=sections,
        estimated_duration_seconds=estimated_duration,
        source_claim_count=len(research.claims),
        provenance=ArtifactProvenance.for_content(
            f"script:{research.topic.key}:v1",
            {
                "topic": research.topic,
                "sections": sections,
                "estimated_duration_seconds": estimated_duration,
            },
            config_version=config.config_version,
            config_hash=config.config_hash,
            prompt_version=config.prompt_version,
            provider_model="local/deterministic",
            input_artifact_ids=(f"research:{research.topic.key}:v1",),
        ),
    )


def build_storyboard(config: ProjectConfig, script: Script) -> Storyboard:
    """Create the deterministic local storyboard adapter for a script."""

    scenes = tuple(
        StoryboardScene(
            scene_id=f"scene-{index}",
            script_section_heading=section.heading,
            narration=section.text,
            visual_direction=f"Visualize the central idea of: {section.heading}.",
            duration_seconds=max(1, round(script.estimated_duration_seconds / len(script.sections))),
        )
        for index, section in enumerate(script.sections, start=1)
    )
    script_id = script.provenance.artifact_id if script.provenance else ""
    provenance = ArtifactProvenance.for_content(
        f"storyboard:{script.topic.key}:v1",
        {"scenes": scenes},
        config_version=config.config_version,
        config_hash=config.config_hash,
        prompt_version=config.prompt_version,
        input_artifact_ids=(script_id,) if script_id else (),
        provider_model="local/deterministic",
    )
    return Storyboard(scenes=scenes, provenance=provenance)


def build_asset_manifest(storyboard: Storyboard) -> AssetManifest:
    """Create deterministic asset placeholders without selecting a vendor."""

    assets = tuple(
        AssetReference(
            asset_id=f"{scene.scene_id}-visual",
            asset_type="visual-placeholder",
            uri=f"local://assets/{scene.scene_id}",
        )
        for scene in storyboard.scenes
    )
    storyboard_id = storyboard.provenance.artifact_id if storyboard.provenance else ""
    inherited = storyboard.provenance
    provenance = ArtifactProvenance.for_content(
        f"assets:{storyboard_id or 'storyboard'}:v1",
        {"assets": assets},
        config_version=inherited.config_version if inherited else "",
        config_hash=inherited.config_hash if inherited else "",
        prompt_version=inherited.prompt_version if inherited else "",
        input_artifact_ids=(storyboard_id,) if storyboard_id else (),
        provider_model="local/deterministic",
    )
    return AssetManifest(assets=assets, provenance=provenance)


def create_render_job(storyboard: Storyboard, asset_manifest: AssetManifest) -> RenderJob:
    """Create a queued render job for a provider adapter."""

    storyboard_id = storyboard.provenance.artifact_id if storyboard.provenance else ""
    assets_id = asset_manifest.provenance.artifact_id if asset_manifest.provenance else ""
    inherited = storyboard.provenance or asset_manifest.provenance
    job_id = f"render:{storyboard_id or 'storyboard'}:v1"
    provenance = ArtifactProvenance.for_content(
        job_id,
        {"storyboard": storyboard_id, "asset_manifest": assets_id},
        config_version=inherited.config_version if inherited else "",
        config_hash=inherited.config_hash if inherited else "",
        prompt_version=inherited.prompt_version if inherited else "",
        input_artifact_ids=tuple(
            artifact_id for artifact_id in (storyboard_id, assets_id) if artifact_id
        ),
        provider_model="local/deterministic",
    )
    return RenderJob(
        job_id=job_id,
        storyboard=storyboard,
        asset_manifest=asset_manifest,
        provenance=provenance,
    )


def publish_video(render_job: RenderJob, uri: str) -> PublishedVideo:
    """Create an unapproved video artifact after a successful render."""

    if render_job.status != RenderJobStatus.SUCCEEDED:
        raise ValueError("Only succeeded render jobs can produce a published video.")
    provenance = ArtifactProvenance.for_content(
        f"video:{render_job.job_id}:v1",
        {"uri": uri},
        config_version=(
            render_job.provenance.config_version if render_job.provenance else ""
        ),
        config_hash=render_job.provenance.config_hash if render_job.provenance else "",
        prompt_version=(
            render_job.provenance.prompt_version if render_job.provenance else ""
        ),
        input_artifact_ids=(render_job.job_id,),
        provider_model="local/deterministic",
        approval_state=ApprovalState.PENDING,
    )
    return PublishedVideo(
        video_id=f"video:{render_job.job_id}:v1",
        render_job_id=render_job.job_id,
        uri=uri,
        provenance=provenance,
    )


def create_episode_draft(config: ProjectConfig, history: LessonHistory) -> EpisodeDraft:
    topic = select_topic(config, history)
    research = build_research_packet(topic)
    script = build_script(config, research)
    return EpisodeDraft(topic=topic, research=research, script=script)


def record_completed_episode(draft: EpisodeDraft, history: LessonHistory) -> None:
    history.record(draft.topic)


def _section_text(heading: str, research: ResearchPacket) -> str:
    if heading == "The idea":
        return research.summary
    if heading == "One thing worth remembering":
        return f"Remember the central question: what does {research.topic.title} help us explain?"
    return f"{heading}: develop this section from the verified claims about {research.topic.title}."
