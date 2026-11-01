"""Private local object-storage substitute with checksum verification."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredObject:
    key: str
    path: Path
    size: int
    checksum: str


class LocalObjectStorage:
    """Content-addressed private storage for local development."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, key: str, source: str | Path) -> StoredObject:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        return self.describe(key)

    def describe(self, key: str) -> StoredObject:
        path = self.root / key
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return StoredObject(key, path, path.stat().st_size, digest)

    def verify(self, stored: StoredObject) -> bool:
        current = self.describe(stored.key)
        return current.size == stored.size and current.checksum == stored.checksum
