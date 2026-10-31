"""Small local lesson-history store used before database persistence exists."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .contracts import Topic


class LessonHistory:
    """Persist completed topics as JSON and prevent normalized duplicates."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._topics = self._read()

    def has_topic(self, topic: Topic) -> bool:
        return topic.key in self._topics

    def record(self, topic: Topic) -> None:
        self._topics.add(topic.key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(sorted(self._topics), indent=2) + "\n", encoding="utf-8"
        )

    def _read(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read lesson history {self.path}: {exc}") from exc
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError(f"Lesson history {self.path} must contain an array of strings.")
        return {_normalize(item) for item in value}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
