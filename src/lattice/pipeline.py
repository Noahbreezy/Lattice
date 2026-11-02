"""Local, provider-independent content pipeline for development and tests."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
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
from .research import (
    AILesson,
    AILessonProvider,
    create_configured_lesson_provider,
)
from .visuals import IllustratedVisualProvider, VisualProvider


@dataclass(frozen=True)
class EpisodeDraft:
    topic: Topic
    research: ResearchPacket
    script: Script


@dataclass(frozen=True)
class ProductionBundle:
    """All deterministic artifacts needed to render one reviewable episode."""

    draft: EpisodeDraft
    storyboard: Storyboard
    asset_manifest: AssetManifest
    render_job: RenderJob


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


def build_demo_research_packet(topic: Topic) -> ResearchPacket:
    """Return source-linked teaching material for the two initial demo topics.

    This is deliberately a small fixture for validating the complete product
    loop. It is not a substitute for a live research provider.
    """

    key = topic.key
    if "path dependence" in key:
        sources = (
            Source(
                "Path dependence",
                "Stanford Encyclopedia of Philosophy, entry on path dependence.",
                "https://plato.stanford.edu/entries/path-dependence/",
                "reference",
            ),
            Source(
                "Increasing returns and the path dependence of progress",
                "Arthur, W. Brian (1994), University of Michigan Press.",
                "https://press.umich.edu/Books/A/Increasing-Returns-and-Path-Dependence",
                "book",
            ),
        )
        claims = (
            Claim(
                "Early choices can influence which options remain practical later.",
                "supported",
                (0, 1),
                "The strength of lock-in varies by technology and institution.",
            ),
            Claim(
                "Network effects, learning, and switching costs can reinforce an established choice.",
                "supported",
                (1,),
            ),
        )
        summary = (
            "Path dependence means that history can constrain present choices. "
            "An early advantage may grow through learning, complementary infrastructure, "
            "network effects, and switching costs, so the outcome is shaped by sequence "
            "as well as by the isolated quality of each option."
        )
    elif "base rate" in key:
        sources = (
            Source(
                "Base rate fallacy",
                "NIST/SEMATECH e-Handbook of Statistical Methods, Bayes theorem.",
                "https://www.itl.nist.gov/div898/handbook/",
                "reference",
            ),
            Source(
                "Understanding diagnostic test results",
                "National Cancer Institute, cancer screening and false positives.",
                "https://www.cancer.gov/about-cancer/screening/understanding-screening-tests",
                "public-health",
            ),
        )
        claims = (
            Claim(
                "The meaning of evidence depends on how common the underlying event was beforehand.",
                "supported",
                (0, 1),
            ),
            Claim(
                "A highly accurate test can still produce many false positives when the target is rare.",
                "supported",
                (1,),
                "Exact predictive values depend on prevalence and test characteristics.",
            ),
        )
        summary = (
            "A base rate is the background frequency of an event before new evidence "
            "arrives. Bayes' rule combines that starting probability with the reliability "
            "of the evidence, which is why rare-event detectors can generate many false alarms."
        )
    else:
        return build_research_packet(topic)
    return ResearchPacket(
        topic=topic,
        summary=summary,
        sources=sources,
        claims=claims,
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


def build_script_from_lesson(
    config: ProjectConfig, lesson: AILesson, words_per_minute: int = 150
) -> Script:
    """Convert model-authored lesson sections into the production script."""

    if tuple(section.heading for section in lesson.sections) != tuple(config.required_sections):
        raise ValueError("AI lesson headings do not match the configured structure.")
    word_count = sum(len(section.text.split()) for section in lesson.sections)
    estimated_duration = max(1, round(word_count / words_per_minute * 60))
    return Script(
        topic=lesson.topic,
        sections=lesson.sections,
        estimated_duration_seconds=estimated_duration,
        source_claim_count=len(lesson.claims),
        provenance=ArtifactProvenance.for_content(
            f"script:{lesson.topic.key}:ai-v1",
            {"sections": lesson.sections, "summary": lesson.summary},
            config_version=config.config_version,
            config_hash=config.config_hash,
            prompt_version=config.prompt_version,
            provider_model=lesson.provider_model,
        ),
    )


def build_storyboard(config: ProjectConfig, script: Script) -> Storyboard:
    """Create the deterministic local storyboard adapter for a script."""

    total_duration = config.video_length_seconds
    base, remainder = divmod(total_duration, len(script.sections))
    scenes = tuple(
        StoryboardScene(
            scene_id=f"scene-{index}",
            script_section_heading=section.heading,
            narration=section.text,
            visual_direction=_visual_direction(section.heading, script.topic),
            duration_seconds=base + (1 if index <= remainder else 0),
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


def _visual_direction(heading: str, topic: Topic) -> str:
    """Create a stable visual brief that can later be sent to a media provider."""

    return (
        f"Vertical educational explainer visual for '{topic.title}': "
        f"show the concrete idea from the section '{heading}', with restrained "
        "motion, readable labels, and consistent navy/amber editorial styling."
    )


def build_asset_manifest(
    storyboard: Storyboard,
    output_dir: str | None = None,
    visual_provider: VisualProvider | None = None,
) -> AssetManifest:
    """Create deterministic asset placeholders without selecting a vendor."""

    if output_dir is not None:
        provider = visual_provider or IllustratedVisualProvider()
        assets = tuple(provider.create(scene, output_dir) for scene in storyboard.scenes)
    else:
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


def build_production_bundle(
    config: ProjectConfig,
    history: LessonHistory,
    research_provider: Callable[[Topic], ResearchPacket] | None = None,
    lesson_provider: AILessonProvider | None = None,
    offline: bool = False,
) -> ProductionBundle:
    """Build a complete provider-neutral render bundle for one episode.

    Offline mode is reserved for deterministic fixtures and tests. Production
    execution uses the configured lesson provider unless one is injected.
    """

    topic = select_topic(config, history)
    if lesson_provider is not None:
        configured_provider = lesson_provider
    elif offline:
        configured_provider = None
    else:
        configured_provider = create_configured_lesson_provider(config)
    if configured_provider is not None:
        lesson = configured_provider.generate_lesson(topic, config)
        research = lesson.to_research_packet()
        script = build_script_from_lesson(config, lesson)
    else:
        research = (
            research_provider(topic)
            if research_provider is not None
            else build_demo_research_packet(topic)
        )
        script = build_script(config, research)
    draft = EpisodeDraft(topic=topic, research=research, script=script)
    storyboard = build_storyboard(config, draft.script)
    assets = build_asset_manifest(storyboard)
    return ProductionBundle(
        draft=draft,
        storyboard=storyboard,
        asset_manifest=assets,
        render_job=create_render_job(storyboard, assets),
    )


def regenerate_scenes(
    storyboard: Storyboard,
    scene_ids: set[str],
    feedback: str,
) -> Storyboard:
    """Create a new storyboard revision while preserving unaffected scenes."""

    if not feedback.strip():
        raise ValueError("Scene regeneration feedback is required.")
    scenes = tuple(
        StoryboardScene(
            scene_id=scene.scene_id,
            script_section_heading=scene.script_section_heading,
            narration=scene.narration,
            visual_direction=(
                scene.visual_direction
                + f" Revise this scene using reviewer feedback: {feedback.strip()}"
                if scene.scene_id in scene_ids
                else scene.visual_direction
            ),
            duration_seconds=scene.duration_seconds,
        )
        for scene in storyboard.scenes
    )
    return Storyboard(scenes=scenes, version=storyboard.version + 1)


def record_completed_episode(draft: EpisodeDraft, history: LessonHistory) -> None:
    history.record(draft.topic)


def _section_text(heading: str, research: ResearchPacket) -> str:
    if heading == "The idea":
        return research.summary
    if heading == "One thing worth remembering":
        return f"Remember the central question: what does {research.topic.title} help us explain?"
    return f"{heading}: develop this section from the verified claims about {research.topic.title}."
