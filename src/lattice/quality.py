"""Deterministic quality checks for scripts before media production."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ProjectConfig
from .contracts import ResearchPacket, Script
from .research import AILesson, validate_research


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str


@dataclass(frozen=True)
class QualityReport:
    issues: tuple[QualityIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


_UNSUPPORTED_CERTAINTY = (
    "always",
    "never",
    "proves",
    "undeniable",
    "undoubtedly",
    "obviously",
    "certainly",
)


def check_lesson(
    config: ProjectConfig,
    lesson: AILesson,
    *,
    min_section_words: int = 5,
    max_section_words: int = 120,
    min_lesson_words: int = 60,
    max_lesson_words: int | None = None,
    min_claims: int = 3,
    max_claims: int = 8,
) -> QualityReport:
    """Validate model-authored lesson content before it enters production."""

    issues: list[QualityIssue] = []
    if not lesson.summary.strip():
        issues.append(QualityIssue("summary", "Lesson summary must be non-empty."))
    expected = tuple(config.required_sections)
    actual = tuple(section.heading for section in lesson.sections)
    if actual != expected:
        issues.append(
            QualityIssue(
                "required-sections",
                "Lesson headings do not match the configured structure.",
            )
        )

    section_word_counts = tuple(
        len(section.text.split()) for section in lesson.sections
    )
    if any(
        count < min_section_words or count > max_section_words
        for count in section_word_counts
    ):
        issues.append(
            QualityIssue(
                "section-length",
                f"Each lesson section must contain {min_section_words}-{max_section_words} words.",
            )
        )

    visual_word_counts = tuple(
        len(section.visual_description.split()) for section in lesson.sections
    )
    if any(count < 25 for count in visual_word_counts):
        issues.append(
            QualityIssue(
                "visual-description",
                "Every lesson section must include a specific visual description "
                "of at least 25 words for video generation.",
            )
        )
    lesson_word_count = sum(section_word_counts)
    if max_lesson_words is None:
        max_lesson_words = config.max_video_length_seconds * 150 // 60
    if not min_lesson_words <= lesson_word_count <= max_lesson_words:
        issues.append(
            QualityIssue(
                "lesson-length",
                f"Lesson text must contain {min_lesson_words}-{max_lesson_words} words.",
            )
        )

    claim_count = len(lesson.claims)
    if not min_claims <= claim_count <= max_claims:
        issues.append(
            QualityIssue(
                "claim-count",
                f"Lesson must contain {min_claims}-{max_claims} claims.",
            )
        )
    if any(
        claim.evidence_level.lower() != "model-generated" for claim in lesson.claims
    ):
        issues.append(
            QualityIssue(
                "unsupported-evidence-label",
                "Model-authored claims must be labelled model-generated until externally verified.",
            )
        )
    statements = [claim.statement for claim in lesson.claims] + [
        section.text for section in lesson.sections
    ]
    if any(
        re.search(
            r"\b(?:18|19|20)\d{2}\b|\b\d+(?:\.\d+)?\s*(?:%|percent|million|billion)\b",
            statement,
            re.IGNORECASE,
        )
        for statement in statements
    ):
        issues.append(
            QualityIssue(
                "unsourced-quantitative-claim",
                "Model-authored dates, percentages, and large quantities need external verification.",
            )
        )
    if not lesson.uncertainty.strip():
        issues.append(
            QualityIssue(
                "uncertainty", "Lesson must state its uncertainty or scope plainly."
            )
        )

    content = " ".join(
        [lesson.summary, lesson.uncertainty]
        + [section.text for section in lesson.sections]
        + [claim.statement for claim in lesson.claims]
    ).lower()
    placeholder_terms = ("placeholder", "lorem ipsum", "todo", "tbd")
    if any(term in content for term in placeholder_terms):
        issues.append(
            QualityIssue(
                "placeholder-content",
                "Lesson contains placeholder or unfinished content.",
            )
        )
    certainty_terms = tuple(
        term
        for term in _UNSUPPORTED_CERTAINTY
        if re.search(rf"\b{re.escape(term)}\b", content)
    )
    if certainty_terms:
        issues.append(
            QualityIssue(
                "unsupported-certainty",
                "Lesson contains unsupported certainty language: "
                + ", ".join(certainty_terms)
                + ".",
            )
        )
    return QualityReport(tuple(issues))


def require_lesson_quality(
    config: ProjectConfig,
    lesson: AILesson,
    **limits: int,
) -> None:
    """Raise a clear error when model-authored lesson content fails validation."""

    report = check_lesson(config, lesson, **limits)
    if not report.passed:
        raise ValueError("; ".join(issue.message for issue in report.issues))


def check_script(
    config: ProjectConfig,
    research: ResearchPacket,
    script: Script,
) -> QualityReport:
    """Check structure, duration, and evidence before storyboard generation."""

    issues: list[QualityIssue] = []
    expected = tuple(config.required_sections)
    actual = tuple(section.heading for section in script.sections)
    if actual != expected:
        issues.append(
            QualityIssue(
                "required-sections",
                "Script headings do not match the configured structure.",
            )
        )
    if script.estimated_duration_seconds > config.max_video_length_seconds:
        issues.append(
            QualityIssue(
                "duration",
                "Estimated duration must be no more than "
                f"{config.max_video_length_seconds} seconds (strictly under three minutes).",
            )
        )
    if script.source_claim_count != len(research.claims):
        issues.append(
            QualityIssue(
                "claim-count", "Script claim count does not match the research packet."
            )
        )
    if any(len(section.visual_description.split()) < 25 for section in script.sections):
        issues.append(
            QualityIssue(
                "visual-description",
                "Every script section must include a specific visual description "
                "of at least 25 words.",
            )
        )
    issues.extend(
        QualityIssue(issue.code, issue.message) for issue in validate_research(research)
    )
    return QualityReport(tuple(issues))


def require_script_quality(
    config: ProjectConfig,
    research: ResearchPacket,
    script: Script,
) -> None:
    """Raise a clear error when a script fails deterministic quality checks."""

    report = check_script(config, research, script)
    if not report.passed:
        raise ValueError("; ".join(issue.message for issue in report.issues))
