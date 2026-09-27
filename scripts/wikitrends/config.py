"""Central configuration: paths, network settings and analysis thresholds.

Everything tunable lives here so that behaviour is easy to audit and change.
Thresholds are documented for humans in references/methodology.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import __version__

SKILL_NAME = "wikipedia-interest-research"
VERSION = __version__

# scripts/wikitrends/config.py -> skill root
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets"

# Wikimedia asks every API client to identify itself with a contact
# (https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).
# Clients without one are treated as "unidentified" and limited to 10 req/min.
DEFAULT_CONTACT = "https://github.com/eaglee26/wikipedia-interest-research"


def user_agent() -> str:
    contact = os.environ.get("WIKI_RESEARCH_CONTACT", "").strip() or DEFAULT_CONTACT
    import platform

    return f"{SKILL_NAME}/{VERSION} ({contact}) Python-urllib/{platform.python_version()}"


# --- Endpoints -------------------------------------------------------------
PAGEVIEWS_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
FIRST_DATA_DAY = "20150701"  # Pageviews API has no data before 2015-07-01

# --- Network behaviour ------------------------------------------------------
# Wikimedia allows ~200 req/min for identified clients; stay well below it.
RATE_PER_MIN = int(os.environ.get("WIKI_RESEARCH_RATE_PER_MIN", "150"))
MAX_WORKERS = 4
HTTP_TIMEOUT_S = 25
HTTP_RETRIES = 4
MAX_RETRY_AFTER_S = 60

# --- Cache ---------------------------------------------------------------------
# Past daily numbers never change, so they are cached forever. Days younger
# than this are re-fetched if the cached copy is older than STALE_AFTER_HOURS.
RECENT_DAYS = 4
STALE_AFTER_HOURS = 12
RESOLVE_TTL_DAYS = 14


def cache_dir() -> Path:
    env = os.environ.get("WIKI_RESEARCH_CACHE")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / SKILL_NAME


def default_out_dir() -> Path:
    env = os.environ.get("WIKI_RESEARCH_OUT")
    return Path(env).expanduser() if env else Path.cwd() / "wiki-research"


# --- Analysis thresholds -----------------------------------------------------------
# See references/methodology.md for the reasoning behind each number.
THRESHOLDS = {
    # average monthly views of a language basket over the last 12 months
    "volume_critical": 100,
    "volume_warn": 1000,
    # |change| below this counts as "stable"
    "change_threshold": 0.10,
    # of the last 12 months, how many must beat the same month a year earlier
    "consistency_up": 8,
    "consistency_down": 4,
    # Mann-Kendall significance level
    "mk_alpha": 0.10,
    # a day is a spike if views > multiplier x rolling 28-day median (and >= floor)
    "spike_multiplier": 4.0,
    "spike_floor": 20,
    # growth is "spike-driven" if spike days carry this share of the recent period's
    # views, or if removing spikes flips/halves the growth
    "spike_share_warn": 0.20,
    # share of basket concepts that must move in the basket's direction
    "breadth_min": 0.6,
    # a series that starts this many months after the window start is "late"
    "late_start_months": 2,
    # peak calendar month average / trough average above this = strong seasonality
    "seasonality_ratio": 2.0,
    # raw vs share growth disagreement worth mentioning (percentage points)
    "platform_gap_pp": 0.15,
}

# Confidence scores used for ranking languages
CONFIDENCE_SCORE = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.2}

DEFAULT_WEIGHTS = {"volume": 0.4, "growth": 0.4, "reliability": 0.2}
