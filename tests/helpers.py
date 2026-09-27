"""Shared test helpers: import paths, temp env, synthetic series."""

from __future__ import annotations

import calendar
import math
import os
import random
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("WIKI_RESEARCH_TODAY", "2026-09-27")
_TMP = tempfile.mkdtemp(prefix="wiki-tests-")
os.environ.setdefault("WIKI_RESEARCH_CACHE", str(Path(_TMP) / "cache"))
os.environ.setdefault("MPLCONFIGDIR", str(Path(_TMP) / "mpl"))

import numpy as np  # noqa: E402

from wikitrends.dates import Window  # noqa: E402


def window(start=(2023, 9), end=(2026, 8)) -> Window:
    return Window(start, end)


def daily_series(w: Window, base: float, growth_per_year: float = 0.0, season: dict | None = None,
                 noise: float = 0.05, seed: int = 0, start_month: int = 0, spikes: dict | None = None) -> np.ndarray:
    """Synthetic daily views aligned to w.days()."""
    rng = random.Random(seed)
    days = w.days()
    out = np.zeros(len(days))
    d0 = date(int(days[0][:4]), int(days[0][4:6]), 1)
    months = w.months
    for i, d in enumerate(days):
        dd = date(int(d[:4]), int(d[4:6]), int(d[6:]))
        m_idx = months.index(f"{d[:4]}-{d[4:6]}")
        if m_idx < start_month:
            continue
        t = (dd - d0).days / 365.25
        s = 1.0 + (season or {}).get(dd.month, 0.0)
        out[i] = max(0.0, base * math.exp(math.log1p(growth_per_year) * t) * s * (1 + rng.uniform(-noise, noise)))
    for day, value in (spikes or {}).items():
        out[days.index(day)] = value
    return np.round(out)


def flat_totals(w: Window, per_month: float = 1e8) -> np.ndarray:
    return np.full(w.n_months, per_month)


def month_days(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]
