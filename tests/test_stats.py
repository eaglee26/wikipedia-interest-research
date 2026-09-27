import unittest

import numpy as np

import helpers  # noqa: F401
from wikitrends import stats

try:
    from scipy import stats as sps
except ImportError:  # scipy is a dev-only dependency
    sps = None


class TestStats(unittest.TestCase):
    @unittest.skipIf(sps is None, "scipy not installed")
    def test_mann_kendall_matches_scipy_kendalltau(self):
        rng = np.random.default_rng(42)
        for _ in range(100):
            n = int(rng.integers(8, 60))
            y = np.round(rng.normal(size=n).cumsum() * 3)  # ties likely
            ours = stats.mann_kendall(y, continuity=False)
            _tau, p = sps.kendalltau(np.arange(n), y, method="asymptotic")
            self.assertAlmostEqual(ours.p, p, places=10)

    @unittest.skipIf(sps is None, "scipy not installed")
    def test_theil_sen_matches_scipy(self):
        rng = np.random.default_rng(7)
        for _ in range(50):
            y = rng.normal(size=int(rng.integers(5, 40))).cumsum()
            self.assertAlmostEqual(stats.theil_sen(y)[0], sps.theilslopes(y, np.arange(len(y))).slope, places=10)

    def test_seasonal_kendall_ignores_pure_seasonality(self):
        season = np.array([1, 1, 1, 1, 1, 0.5, 0.4, 0.5, 3, 1.5, 1, 1], dtype=float)
        y = np.log(np.tile(season, 3) * 1000)
        self.assertGreater(stats.seasonal_kendall(y).p, 0.5)  # a repeating pattern is not a trend

    def test_seasonal_kendall_detects_trend_under_seasonality(self):
        season = np.array([1, 1, 1, 1, 1, 0.5, 0.4, 0.5, 3, 1.5, 1, 1], dtype=float)
        growth = np.exp(np.arange(36) * np.log(1.25) / 12)
        t = stats.seasonal_kendall(np.log(np.tile(season, 3) * 1000 * growth))
        self.assertLess(t.p, 0.01)
        self.assertEqual(t.direction, 1)
        slope = stats.seasonal_theil_sen(np.log(np.tile(season, 3) * growth))
        self.assertAlmostEqual(np.exp(slope) - 1, 0.25, places=6)

    def test_rolling_median_removes_single_spike(self):
        self.assertEqual(list(stats.rolling_median([1, 1, 1, 50, 1, 1, 1], 3)), [1.0] * 7)


if __name__ == "__main__":
    unittest.main()
