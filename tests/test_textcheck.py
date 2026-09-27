import unittest

import helpers  # noqa: F401
from wikitrends.textcheck import _parse_number, check_text

SUMMARY = {
    "analysis": {
        "window": {"months": 36},
        "languages": {
            "uk": {
                "status": "ok",
                "direction": "declining",
                "comparison": {"k": 12},
                "metrics": {
                    "avg_monthly_views_recent": 559.0,
                    "views_change": -0.5962,
                    "share_change": -0.4643,
                    "share_change_without_spikes": -0.4643,
                    "share_per_million_recent": 8.7,
                    "spike_share": 0.0,
                    "consistency": {"months_up": 2, "of": 12},
                    "trend": {"p": 0.0, "slope_pct_per_year": -44.1},
                },
                "spikes": [],
                "per_concept": {},
                "monthly": {"views": [100] * 36},
            }
        },
        "ranking": [],
    }
}


class TestTextCheck(unittest.TestCase):
    def test_parse_number_formats(self):
        self.assertEqual(_parse_number("1,234"), 1234)
        self.assertEqual(_parse_number("1 234"), 1234)
        self.assertEqual(_parse_number("12,5"), 12.5)
        self.assertEqual(_parse_number("1 234,5"), 1234.5)

    def test_correct_numbers_pass(self):
        text = "Частка впала на 46% (−46,4%), перегляди −60%, ≈559 переглядів/міс; 2 з 12 місяців кращі."
        res = check_text(text, SUMMARY)
        self.assertEqual(res.errors, [])
        self.assertGreaterEqual(res.checked, 4)

    def test_invented_numbers_fail(self):
        res = check_text("Interest fell 37% to 2,345 views per month.", SUMMARY)
        self.assertEqual(len(res.errors), 2)
        self.assertIn("37%", res.errors[0])

    def test_thousands_suffix_and_years_are_handled(self):
        self.assertEqual(check_text("У 2024 і 2026 роках — близько 0,56 тис. переглядів.", SUMMARY).errors, [])

    def test_period_tokens_are_not_millions(self):
        # a free model wrote "(24m, Sep 2024–Aug 2026)"; "24m" is months, "1.2M" is millions
        self.assertEqual(check_text("Italian is steadier (24m, 36 m window).", SUMMARY).errors, [])
        self.assertEqual(len(check_text("About 1.2M views a year.", SUMMARY).errors), 1)

    def test_direction_contradiction_warns_but_negation_is_ok(self):
        self.assertTrue(check_text("Interest is growing fast.", SUMMARY).warnings)
        self.assertEqual(check_text("Інтерес не зростає, а падає.", SUMMARY).warnings, [])


if __name__ == "__main__":
    unittest.main()
