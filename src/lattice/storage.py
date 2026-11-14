"""Private local object-storage substitute with checksum verification."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Callable, Protocol, cast


@dataclass(frozen=True)
class StoredObject:
    key: str
    path: Path | str
    size: int
    checksum: str


class ObjectStorage(Protocol):
    def put_file(self, key: str, source: str | Path) -> StoredObject: ...
    def put_json(self, key: str, value: object) -> StoredObject: ...
    def get_bytes(self, uri: str) -> bytes: ...


class _S3Body(Protocol):
    def read(self) -> bytes: ...


class _S3Client(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object: ...
    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, _S3Body]: ...


class LocalObjectStorage:
    """Content-addressed private storage for local development."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, key: str, source: str | Path) -> StoredObject:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        return self.describe(key)

    def put_json(self, key: str, value: object) -> StoredObject:
        """Store a UTF-8 JSON document suitable for API and frontend clients."""

        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.describe(key)

    def describe(self, key: str) -> StoredObject:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return StoredObject(key, path, path.stat().st_size, digest)

    def verify(self, stored: StoredObject) -> bool:
        current = self.describe(stored.key)
        return current.size == stored.size and current.checksum == stored.checksum

    def get_bytes(self, uri: str) -> bytes:
        path = Path(uri).resolve()
        path.relative_to(self.root.resolve())
        return path.read_bytes()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        path.relative_to(self.root.resolve())
        return path


class S3ObjectStorage:
    """Private S3-compatible storage; never creates public objects or URLs."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        client: _S3Client | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("An object-storage bucket is required.")
        if client is None:
            try:
                factory = cast(Callable[..., _S3Client], getattr(import_module("boto3"), "client"))
            except ImportError as exc:
                raise RuntimeError(
                    "Install lattice-video[server] for S3 support."
                ) from exc
            client = factory("s3", endpoint_url=endpoint_url)
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        if (
            not key
            or key.startswith("/")
            or any(part in {"", ".", ".."} for part in key.split("/"))
        ):
            raise ValueError("Object key must be a safe relative path.")
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_file(self, key: str, source: str | Path) -> StoredObject:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        data = source_path.read_bytes()
        return self._put(key, data)

    def put_json(self, key: str, value: object) -> StoredObject:
        return self._put(
            key, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        )

    def _put(self, key: str, data: bytes) -> StoredObject:
        full_key = self._key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=full_key,
            Body=data,
            ContentType="application/json"
            if key.endswith(".json")
            else "application/octet-stream",
        )
        return StoredObject(
            key,
            f"s3://{self.bucket}/{full_key}",
            len(data),
            hashlib.sha256(data).hexdigest(),
        )

    def get_bytes(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("Object URI is outside the configured bucket.")
        key = uri[len(prefix) :]
        expected_prefix = f"{self.prefix}/" if self.prefix else ""
        if not key.startswith(expected_prefix):
            raise ValueError("Object URI is outside the configured prefix.")
        self._key(key[len(expected_prefix) :])
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
