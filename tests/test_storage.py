import io
import json
import tempfile
import unittest
from pathlib import Path

from lattice.storage import LocalObjectStorage, S3ObjectStorage


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        del ContentType
        bucket, key, body = Bucket, Key, Body
        assert isinstance(bucket, str) and isinstance(key, str)
        assert isinstance(body, bytes)
        self.objects[(bucket, key)] = body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, io.BytesIO]:
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class StorageTests(unittest.TestCase):
    def test_private_s3_round_trip_and_prefix_boundary(self):
        client = FakeS3()
        storage = S3ObjectStorage("review", "lattice", client=client)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"private-video")
            video = storage.put_file("videos/episode/revision-1.mp4", source)
            self.assertEqual(storage.get_bytes(str(video.path)), b"private-video")
            lesson = storage.put_json(
                "lessons/episode/revision-1.json", {"kind": "lesson"}
            )
            self.assertEqual(
                json.loads(storage.get_bytes(str(lesson.path)))["kind"], "lesson"
            )
            self.assertEqual(len(video.checksum), 64)
            with self.assertRaises(ValueError):
                storage.get_bytes("s3://review/other/video.mp4")
            with self.assertRaises(ValueError):
                storage.put_file("../escape.mp4", source)

    def test_local_storage_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalObjectStorage(Path(directory) / "objects")
            with self.assertRaises(ValueError):
                storage.put_json("../outside.json", {})
