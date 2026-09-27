"""Robust trend statistics implemented with numpy only.

- Mann-Kendall trend test (with tie correction)
- Seasonal Kendall test (Hirsch et al., 1982): Mann-Kendall computed per
  calendar month and summed, so a school-year or New-Year pattern cannot be
  mistaken for a trend
- Theil-Sen slope and its seasonal variant

Validated against scipy.stats.kendalltau / theilslopes in tests/test_stats.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _norm_sf(z: float) -> float:
    """Survival function of the standard normal distribution."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _s_and_var(y: np.ndarray) -> tuple[float, float]:
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return 0.0, 0.0
    diff = y[None, :] - y[:, None]  # diff[i, j] = y[j] - y[i]
    iu = np.triu_indices(n, k=1)
    s = float(np.sign(diff[iu]).sum())
    _, counts = np.unique(y, return_counts=True)
    ties = counts[counts > 1]
    var = (n * (n - 1) * (2 * n + 5) - float(np.sum(ties * (ties - 1) * (2 * ties + 5)))) / 18.0
    return s, var


@dataclass
class TrendTest:
    test: str
    s: float
    var: float
    z: float
    p: float  # two-sided
    n: int

    @property
    def direction(self) -> int:
        return 1 if self.s > 0 else (-1 if self.s < 0 else 0)


def _z(s: float, var: float, continuity: bool) -> float:
    if var <= 0:
        return 0.0
    if continuity:
        if s > 0:
            return (s - 1) / math.sqrt(var)
        if s < 0:
            return (s + 1) / math.sqrt(var)
        return 0.0
    return s / math.sqrt(var)


def mann_kendall(y, continuity: bool = True) -> TrendTest:
    y = np.asarray(y, dtype=float)
    s, var = _s_and_var(y)
    z = _z(s, var, continuity)
    return TrendTest("mann-kendall", s, var, z, 2 * _norm_sf(abs(z)), len(y))


def seasonal_kendall(y, period: int = 12, continuity: bool = True) -> TrendTest:
    """Sum of per-season Mann-Kendall statistics. y[i] belongs to season i % period."""
    y = np.asarray(y, dtype=float)
    s_tot, var_tot = 0.0, 0.0
    for k in range(period):
        s, var = _s_and_var(y[k::period])
        s_tot += s
        var_tot += var
    z = _z(s_tot, var_tot, continuity)
    return TrendTest("seasonal-kendall", s_tot, var_tot, z, 2 * _norm_sf(abs(z)), len(y))


def theil_sen(y, x=None) -> tuple[float, float]:
    """Median of pairwise slopes; returns (slope, intercept)."""
    y = np.asarray(y, dtype=float)
    x = np.arange(len(y), dtype=float) if x is None else np.asarray(x, dtype=float)
    n = len(y)
    if n < 2:
        return 0.0, float(y[0]) if n else 0.0
    i, j = np.triu_indices(n, k=1)
    dx = x[j] - x[i]
    ok = dx != 0
    slopes = (y[j] - y[i])[ok] / dx[ok]
    slope = float(np.median(slopes)) if len(slopes) else 0.0
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def seasonal_theil_sen(y, period: int = 12) -> float:
    """Median of slopes between the same season in different cycles (units: per cycle)."""
    y = np.asarray(y, dtype=float)
    slopes = []
    for k in range(period):
        seq = y[k::period]
        for a in range(len(seq)):
            for b in range(a + 1, len(seq)):
                slopes.append((seq[b] - seq[a]) / (b - a))
    return float(np.median(slopes)) if slopes else 0.0


def safe_log(values, floor: float = 0.5) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    return np.log(np.maximum(v, floor))


def rolling_median(values, window: int = 29) -> np.ndarray:
    """Centered rolling median (window clipped at the edges)."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    half = window // 2
    out = np.empty(n)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        out[i] = np.median(v[lo:hi])
    return out
