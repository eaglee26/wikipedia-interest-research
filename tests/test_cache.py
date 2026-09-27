import tempfile
import unittest
from datetime import date
from pathlib import Path

import helpers  # noqa: F401
from wikitrends.cache import Cache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = Cache(Path(self.dir) / "c.sqlite3", today=date(2026, 9, 27))

    def tearDown(self):
        self.cache.close()

    def test_missing_range_then_covered_and_zero_filled(self):
        key = ("pl.wikipedia", "Astronomia")
        self.assertEqual(self.cache.missing_range(*key, "20250101", "20250110"), ("20250101", "20250110"))
        self.cache.store_daily(*key, "20250101", "20250110", {"20250102": 5, "20250105": 7})
        self.assertIsNone(self.cache.missing_range(*key, "20250101", "20250110"))
        got = self.cache.get_daily(*key, "20250101", "20250110")
        self.assertEqual(got["20250102"], 5)
        self.assertEqual(got["20250103"], 0)  # absent from API response = genuine zero
        self.assertEqual(len(got), 10)

    def test_partial_extension_fetches_only_new_days(self):
        key = ("pl.wikipedia", "Astronomia")
        self.cache.store_daily(*key, "20250101", "20250110", {})
        self.assertEqual(self.cache.missing_range(*key, "20250101", "20250120"), ("20250111", "20250120"))

    def test_monthly_agg_and_known_missing(self):
        self.cache.store_monthly_agg("pl.wikipedia", {"2025-01": 10, "2025-02": 20}, "20250101", "20250228")
        self.assertEqual(self.cache.get_monthly_agg("pl.wikipedia", ["2025-01", "2025-02"]), {"2025-01": 10, "2025-02": 20})
        self.cache.store_monthly_agg("xx.wikipedia", {}, "20250101", "20250228", status=404)
        self.assertTrue(self.cache.agg_known_missing("xx.wikipedia"))

    def test_kv_ttl(self):
        self.cache.kv_set("k", {"a": 1})
        self.assertEqual(self.cache.kv_get("k"), {"a": 1})
        self.assertIsNone(self.cache.kv_get("k", ttl_days=-1))


if __name__ == "__main__":
    unittest.main()
