"""Local, provider-independent content pipeline for development and tests."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ProjectConfig
from .contracts import Claim, ResearchPacket, Script, ScriptSection, Source, Topic, now_utc
from .history import LessonHistory


@dataclass(frozen=True)
class EpisodeDraft:
    topic: Topic
    research: ResearchPacket
    script: Script


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
