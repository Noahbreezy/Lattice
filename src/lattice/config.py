"""Load and validate project configuration without requiring external services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a project configuration is missing or invalid."""


@dataclass(frozen=True)
class RetentionSettings:
    """Optional video-count limits; ``None`` means unlimited."""

    max_cloud_videos: int | None = 100
    max_server_videos: int | None = 5
    max_approved_videos: int | None = 100
    max_rejected_videos: int | None = 20
    max_awaiting_review_videos: int | None = 10

    def __post_init__(self) -> None:
        for field in (
            "max_cloud_videos",
            "max_server_videos",
            "max_approved_videos",
            "max_rejected_videos",
            "max_awaiting_review_videos",
        ):
            limit = getattr(self, field)
            if limit is not None and (
                not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
            ):
                raise ConfigError(
                    f"{field} must be a non-negative integer or null."
                )


@dataclass(frozen=True)
class ProjectConfig:
    """Validated configuration shared by planning, writing, and production stages."""

    name: str
    description: str
    channel_name: str
    format: str
    video_length_seconds: int
    lesson_prompt: str
    traits: tuple[str, ...]
    required_sections: tuple[str, ...]
    subject_areas: tuple[str, ...]
    learning_rules: tuple[str, ...]
    topic_seeds: tuple[dict[str, str], ...]
    ai_tools: tuple[dict[str, Any], ...]
    workflow: tuple[str, ...]
    retention: RetentionSettings = RetentionSettings()

    @classmethod
    def from_mapping(cls, raw: MappingLike) -> "ProjectConfig":
        if not isinstance(raw, dict):
            raise ConfigError("The project configuration must be a JSON object.")

        project = _required_object(raw, "project")
        content = _required_object(raw, "content")
        production = _required_object(raw, "production")

        name = _required_string(project, "name", "project")
        description = _required_string(project, "description", "project")
        channel_name = _required_string(content, "channel_name", "content")
        format_name = _required_string(content, "format", "content")
        lesson_prompt = _required_string(content, "prompt", "content")
        video_length_seconds = production.get("video_length_seconds")
        if (
            not isinstance(video_length_seconds, int)
            or isinstance(video_length_seconds, bool)
            or not 1 <= video_length_seconds <= 3600
        ):
            raise ConfigError(
                "production.video_length_seconds must be an integer from 1 to 3600."
            )

        traits = _required_strings(production, "traits", "production")
        required_sections = _required_strings(content, "required_sections", "content")
        subject_areas = _required_strings(content, "subject_areas", "content")
        learning_rules = _required_strings(content, "learning_rules", "content")
        topic_seeds = _optional_topic_seeds(content.get("topic_seeds"))
        workflow = _required_strings(production, "workflow", "production")
        ai_tools = _required_tools(production.get("ai_tools"))
        retention = _optional_retention(production.get("retention"))

        return cls(
            name=name,
            description=description,
            channel_name=channel_name,
            format=format_name,
            video_length_seconds=video_length_seconds,
            lesson_prompt=lesson_prompt,
            traits=traits,
            required_sections=required_sections,
            subject_areas=subject_areas,
            learning_rules=learning_rules,
            topic_seeds=topic_seeds,
            ai_tools=ai_tools,
            workflow=workflow,
            retention=retention,
        )


MappingLike = dict[str, Any]


def load_config(path: str | Path) -> ProjectConfig:
    """Read a UTF-8 JSON configuration file and return its validated model."""

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {config_path}: {exc.msg}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {config_path}: {exc}") from exc

    return ProjectConfig.from_mapping(raw)


def _required_object(raw: MappingLike, key: str) -> MappingLike:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be an object.")
    return value


def _required_string(raw: MappingLike, key: str, section: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{section}.{key} must be a non-empty string.")
    return value.strip()


def _required_strings(raw: MappingLike, key: str, section: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{section}.{key} must be a non-empty array of strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError(f"{section}.{key} must contain only non-empty strings.")
    return tuple(item.strip() for item in value)


def _required_tools(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise ConfigError("production.ai_tools must be an array.")
    tools: list[dict[str, Any]] = []
    for index, tool in enumerate(value):
        if not isinstance(tool, dict):
            raise ConfigError(f"production.ai_tools[{index}] must be an object.")
        name = tool.get("name")
        purpose = tool.get("purpose")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(
                f"production.ai_tools[{index}].name must be a non-empty string."
            )
        if not isinstance(purpose, str) or not purpose.strip():
            raise ConfigError(
                f"production.ai_tools[{index}].purpose must be a non-empty string."
            )
        tools.append(dict(tool))
    return tuple(tools)


def _optional_topic_seeds(value: Any) -> tuple[dict[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("content.topic_seeds must be an array.")
    topics: list[dict[str, str]] = []
    for index, topic in enumerate(value):
        if not isinstance(topic, dict):
            raise ConfigError(f"content.topic_seeds[{index}] must be an object.")
        title = topic.get("title")
        subject_area = topic.get("subject_area")
        if not isinstance(title, str) or not title.strip():
            raise ConfigError(
                f"content.topic_seeds[{index}].title must be a non-empty string."
            )
        if not isinstance(subject_area, str) or not subject_area.strip():
            raise ConfigError(
                f"content.topic_seeds[{index}].subject_area must be a non-empty string."
            )
        topics.append({"title": title.strip(), "subject_area": subject_area.strip()})
    return tuple(topics)


def _optional_retention(value: Any) -> RetentionSettings:
    if value is None:
        return RetentionSettings()
    if not isinstance(value, dict):
        raise ConfigError("production.retention must be an object.")
    fields = (
        "max_cloud_videos",
        "max_server_videos",
        "max_approved_videos",
        "max_rejected_videos",
        "max_awaiting_review_videos",
    )
    limits: dict[str, int | None] = {}
    for field in fields:
        limit = value.get(field)
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise ConfigError(
                f"production.retention.{field} must be a non-negative integer or null."
            )
        limits[field] = limit
    return RetentionSettings(**limits)
