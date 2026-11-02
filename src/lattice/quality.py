"""Deterministic quality checks for scripts before media production."""

from __future__ import annotations

from dataclasses import dataclass
import re

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
    max_lesson_words: int = 350,
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
            QualityIssue("required-sections", "Lesson headings do not match the configured structure.")
        )

    section_word_counts = tuple(len(section.text.split()) for section in lesson.sections)
    if any(count < min_section_words or count > max_section_words for count in section_word_counts):
        issues.append(
            QualityIssue(
                "section-length",
                f"Each lesson section must contain {min_section_words}-{max_section_words} words.",
            )
        )
    lesson_word_count = sum(section_word_counts)
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
    if not lesson.uncertainty.strip():
        issues.append(
            QualityIssue("uncertainty", "Lesson must state its uncertainty or scope plainly.")
        )

    content = " ".join(
        [lesson.summary, lesson.uncertainty]
        + [section.text for section in lesson.sections]
        + [claim.statement for claim in lesson.claims]
    ).lower()
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
    duration_tolerance: float = 0.25,
) -> QualityReport:
    """Check structure, duration, and evidence before storyboard generation."""

    issues: list[QualityIssue] = []
    expected = tuple(config.required_sections)
    actual = tuple(section.heading for section in script.sections)
    if actual != expected:
        issues.append(
            QualityIssue("required-sections", "Script headings do not match the configured structure.")
        )
    lower_bound = config.video_length_seconds * (1 - duration_tolerance)
    upper_bound = config.video_length_seconds * (1 + duration_tolerance)
    if not lower_bound <= script.estimated_duration_seconds <= upper_bound:
        issues.append(
            QualityIssue(
                "duration",
                f"Estimated duration must be between {lower_bound:.0f} and {upper_bound:.0f} seconds.",
            )
        )
    if script.source_claim_count != len(research.claims):
        issues.append(
            QualityIssue("claim-count", "Script claim count does not match the research packet.")
        )
    issues.extend(
        QualityIssue(issue.code, issue.message)
        for issue in validate_research(research)
    )
    return QualityReport(tuple(issues))


def require_script_quality(
    config: ProjectConfig,
    research: ResearchPacket,
    script: Script,
    duration_tolerance: float = 0.25,
) -> None:
    """Raise a clear error when a script fails deterministic quality checks."""

    report = check_script(config, research, script, duration_tolerance)
    if not report.passed:
        raise ValueError("; ".join(issue.message for issue in report.issues))
