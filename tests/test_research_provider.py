from __future__ import annotations

import json
import unittest
from urllib.request import Request

from lattice.contracts import Topic
from lattice.research import WikipediaResearchProvider


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "extract": "Path dependence describes how earlier choices influence later options.",
                "content_urls": {
                    "desktop": {"page": "https://en.wikipedia.org/wiki/Path_dependence"}
                },
            }
        ).encode()


class ResearchProviderTests(unittest.TestCase):
    def test_wikipedia_provider_creates_source_linked_packet(self):
        def opener(request: Request, *, timeout: int) -> _Response:
            del request, timeout
            return _Response()
        provider = WikipediaResearchProvider(
            opener=opener
        )
        packet = provider.research(Topic("Path dependence", "systems"))
        self.assertEqual(packet.claims[0].source_indices, (0,))
        self.assertEqual(packet.sources[0].source_type, "encyclopedia")
