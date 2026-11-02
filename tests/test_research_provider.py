import json
import unittest

from lattice.contracts import Topic
from lattice.research import WikipediaResearchProvider


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps({
            "extract": "Path dependence describes how earlier choices influence later options.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Path_dependence"}},
        }).encode()


class ResearchProviderTests(unittest.TestCase):
    def test_wikipedia_provider_creates_source_linked_packet(self):
        provider = WikipediaResearchProvider(opener=lambda *_args, **_kwargs: _Response())
        packet = provider.research(Topic("Path dependence", "systems"))
        self.assertEqual(packet.claims[0].source_indices, (0,))
        self.assertEqual(packet.sources[0].source_type, "encyclopedia")
