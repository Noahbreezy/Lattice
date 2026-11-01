"""Deterministic quality checks for scripts before media production."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ProjectConfig
from .contracts import ResearchPacket, Script
from .research import validate_research


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
