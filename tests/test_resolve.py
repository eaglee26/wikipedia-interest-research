import tempfile
import unittest
from datetime import date
from pathlib import Path

import helpers  # noqa: F401
from fakes import FakeWikimedia, load
from wikitrends.cache import Cache
from wikitrends.net import HttpClient
from wikitrends.resolve import broader_concepts, rank, resolve_topics, split_topics


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.fake = FakeWikimedia()
        self.client = HttpClient(transport=self.fake, sleep=lambda s: None, rate_per_min=100000)
        self.cache = Cache(Path(tempfile.mkdtemp()) / "c.sqlite3", today=date(2026, 9, 27))

    def tearDown(self):
        self.cache.close()

    def test_rank_prefers_widespread_concept_over_first_hit(self):
        raw = [
            {"id": r["id"], "label": r["label"], "description": r["description"],
             "match_type": r["match"]["type"], "match_text": r["match"]["text"], "aliases": []}
            for r in load("real_wd_search_mercury_en.json")["search"]
        ]
        counts = {p["title"]: int(p["pageprops"]["wb-sitelinks"]) for p in load("real_wd_pageprops_sitelinks.json")["query"]["pages"]}
        best, alts, ambiguous, weak = rank("Mercury", raw, counts)
        self.assertEqual(best.qid, "Q308")  # the planet, not the car brand listed first by Wikidata
        self.assertTrue(ambiguous)  # chemical element Q925 is also widespread
        self.assertIn("Q925", [a.qid for a in alts])
        self.assertFalse(weak)

    def test_intermittent_fasting_missing_in_polish(self):
        concepts, _notes = resolve_topics(self.client, self.cache, ["intermittent fasting"], ["pl", "cs"])
        c = concepts[0]
        self.assertEqual(c.qid, "Q1666254")
        self.assertIsNone(c.titles["pl"])  # real fact: no Polish article
        self.assertEqual(c.titles["cs"], "Přerušovaný půst")
        self.assertFalse(c.ambiguous)

    def test_cyrillic_query_searches_in_ukrainian(self):
        concepts, _ = resolve_topics(self.client, self.cache, ["астрономія"], ["uk", "cs"])
        self.assertEqual(concepts[0].qid, "Q333")
        self.assertEqual(concepts[0].titles, {"uk": "Астрономія", "cs": "Astronomie"})

    def test_duplicate_concepts_are_merged(self):
        concepts, notes = resolve_topics(self.client, self.cache, ["астрономія", "Q333"], ["uk"])
        self.assertEqual(len(concepts), 1)
        self.assertTrue(notes)

    def test_broader_concepts_available_everywhere(self):
        props = broader_concepts(self.client, self.cache, "Q1666254", ["pl", "cs"])
        self.assertEqual([p["qid"] for p in props], ["Q44602"])  # fasting; diet has no cs article
        self.assertEqual(props[0]["titles"], {"pl": "Post", "cs": "Půst"})

    def test_cache_prevents_repeat_requests(self):
        resolve_topics(self.client, self.cache, ["intermittent fasting"], ["pl", "cs"])
        n = len(self.fake.calls)
        resolve_topics(self.client, self.cache, ["intermittent fasting"], ["pl", "cs"])
        self.assertEqual(len(self.fake.calls), n)

    def test_split_topics(self):
        self.assertEqual(split_topics("a, b ,c"), ["a", "b", "c"])
        self.assertEqual(split_topics("Mercury (planet); black hole"), ["Mercury (planet)", "black hole"])


if __name__ == "__main__":
    unittest.main()
