import unittest

import numpy as np

import helpers
from wikitrends.analyze import analyze_language, fmt_pct, rank_languages

W = helpers.window()  # 2023-09 .. 2026-08, 36 months
SCHOOL = {9: 1.5, 10: 0.3, 6: -0.5, 7: -0.6, 8: -0.5}


def run(series: dict, totals=None, basket=None, missing=None):
    basket = basket or list(series)
    totals = helpers.flat_totals(W) if totals is None else totals
    return analyze_language(
        "xx", W, basket, {q: f"title {q}" for q in series}, series, totals, missing or [],
        {q: q for q in list(series) + (missing or [])},
    )


def flag_ids(info):
    return {f["id"] for f in info["flags"]}


class TestVerdicts(unittest.TestCase):
    def test_flat_series_is_stable_with_high_confidence(self):
        info = run({"A": helpers.daily_series(W, 400)})
        self.assertEqual(info["direction"], "stable")
        self.assertEqual(info["confidence"], "HIGH")
        self.assertLess(abs(info["metrics"]["share_change"]), 0.05)

    def test_steady_growth_is_growing_high(self):
        info = run({"A": helpers.daily_series(W, 400, growth_per_year=0.3)})
        self.assertEqual(info["direction"], "growing")
        self.assertEqual(info["confidence"], "HIGH")
        self.assertAlmostEqual(info["metrics"]["share_change"], 0.3, delta=0.05)
        self.assertEqual(info["metrics"]["consistency"]["months_up"], 12)
        self.assertLess(info["metrics"]["trend"]["p"], 0.01)

    def test_seasonality_is_not_mistaken_for_trend(self):
        info = run({"A": helpers.daily_series(W, 400, season=SCHOOL)})
        self.assertEqual(info["direction"], "stable")
        self.assertIn("seasonality", flag_ids(info))
        self.assertIn(9, info["seasonality"]["peak_months"])

    def test_growth_made_of_spikes_is_low_confidence(self):
        days = W.days()
        recent = [d for d in days if d >= "20250901"]
        spikes = {recent[i]: 9000 for i in range(0, 300, 45)}  # 7 viral days, flat otherwise
        info = run({"A": helpers.daily_series(W, 300, spikes=spikes)})
        self.assertIn("spike_driven", flag_ids(info))
        self.assertEqual(info["confidence"], "LOW")
        self.assertLess(abs(info["metrics"]["share_change_without_spikes"]), 0.1)

    def test_single_spike_does_not_flip_a_real_decline(self):
        spikes = {"20250414": 5000}
        info = run({"A": helpers.daily_series(W, 400, growth_per_year=-0.4, spikes=spikes)})
        self.assertEqual(info["direction"], "declining")
        self.assertNotIn("spike_driven", flag_ids(info))
        self.assertIn("spikes_present", flag_ids(info))

    def test_article_created_mid_window_is_flagged(self):
        info = run({"A": helpers.daily_series(W, 400, start_month=14)})
        self.assertIn("late_start", flag_ids(info))
        self.assertEqual(info["confidence"], "LOW")

    def test_low_volume_levels(self):
        self.assertIn("volume_critical", flag_ids(run({"A": helpers.daily_series(W, 2)})))
        self.assertIn("volume_warn", flag_ids(run({"A": helpers.daily_series(W, 15)})))

    def test_platform_effect_when_edition_shrinks(self):
        # article flat in raw views while the whole edition loses 30% per year
        totals = np.array([1e8 * (0.7 ** (i / 12)) for i in range(W.n_months)])
        info = run({"A": helpers.daily_series(W, 400)}, totals=totals)
        self.assertEqual(info["direction"], "growing")  # relative interest rose
        self.assertIn("platform_effect", flag_ids(info))
        self.assertLess(abs(info["metrics"]["views_change"]), 0.05)

    def test_narrow_basket(self):
        info = run({
            "A": helpers.daily_series(W, 400, growth_per_year=0.6, seed=1),
            "B": helpers.daily_series(W, 400, growth_per_year=-0.2, seed=2),
            "C": helpers.daily_series(W, 400, growth_per_year=-0.1, seed=3),
        })
        self.assertIn("narrow", flag_ids(info))

    def test_missing_article_gives_no_data(self):
        info = analyze_language("pl", W, [], {}, {}, helpers.flat_totals(W), ["Q1"], {"Q1": "intermittent fasting"})
        self.assertEqual(info["status"], "no_data")
        self.assertEqual(info["flags"][0]["id"], "no_article")

    def test_short_window_uses_same_months_last_year(self):
        w = helpers.window((2025, 1), (2026, 6))  # 18 months
        s = helpers.daily_series(w, 400, growth_per_year=0.3)
        info = analyze_language("xx", w, ["A"], {"A": "a"}, {"A": s}, helpers.flat_totals(w), [], {"A": "a"})
        self.assertEqual(info["comparison"]["kind"], "yoyk")
        self.assertEqual(info["comparison"]["k"], 6)
        self.assertIn("short_window", flag_ids(info))


class TestRanking(unittest.TestCase):
    def test_weights_change_the_order(self):
        big_flat = run({"A": helpers.daily_series(W, 5000)})
        small_growing = run({"A": helpers.daily_series(W, 300, growth_per_year=0.5)})
        infos = {"pl": big_flat, "cs": small_growing}
        by_volume = rank_languages(infos, {"volume": 0.8, "growth": 0.1, "reliability": 0.1})
        by_growth = rank_languages(infos, {"volume": 0.1, "growth": 0.8, "reliability": 0.1})
        self.assertEqual(by_volume[0]["lang"], "pl")
        self.assertEqual(by_growth[0]["lang"], "cs")
        self.assertIn("largest audience", by_volume[0]["why"])

    def test_fmt_pct(self):
        self.assertEqual(fmt_pct(0.1234), "+12%")
        self.assertEqual(fmt_pct(-0.4696, 1), "-47.0%")
        self.assertEqual(fmt_pct(None), "n/a")


if __name__ == "__main__":
    unittest.main()
