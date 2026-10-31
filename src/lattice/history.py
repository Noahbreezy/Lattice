"""Small local lesson-history store used before database persistence exists."""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .contracts import Topic


class LessonHistory:
    """Persist completed topics as JSON and prevent normalized duplicates."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._topics = self._read()

    def has_topic(self, topic: Topic) -> bool:
        return topic.key in self._topics

    def reserve_next(self, topics: Iterable[Topic]) -> Topic:
        """Atomically reserve the first topic not already in history."""

        with self._lock():
            self._topics = self._read()
            for topic in topics:
                if topic.key not in self._topics:
                    self._topics.add(topic.key)
                    self._write()
                    return topic
        raise ValueError("No unused topic seeds remain; add more topics or start a new project.")

    def record(self, topic: Topic) -> None:
        with self._lock():
            self._topics = self._read()
            self._topics.add(topic.key)
            self._write()

    def _write(self) -> None:
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

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with lock_path.open("a+b") as lock_file:
            if sys.platform == "win32":
                import msvcrt

                lock_file.seek(0)
                lock_file.write(b"0")
                lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if sys.platform == "win32":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
