"""SQLite cache for pageviews and Wikidata/Wikipedia lookups.

Past daily pageviews never change, so they are stored forever and only the
missing days are requested again. Coverage rows record which day ranges were
fetched, so a day that is absent from the API response is known to be a
genuine zero rather than "not fetched yet".

All writes happen from the main thread; network workers only return data.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
    project TEXT NOT NULL, article TEXT NOT NULL, access TEXT NOT NULL, agent TEXT NOT NULL,
    day TEXT NOT NULL, views INTEGER NOT NULL,
    PRIMARY KEY (project, article, access, agent, day)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS daily_cov (
    project TEXT NOT NULL, article TEXT NOT NULL, access TEXT NOT NULL, agent TEXT NOT NULL,
    start TEXT NOT NULL, end TEXT NOT NULL, fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS daily_cov_key ON daily_cov (project, article, access, agent);
CREATE TABLE IF NOT EXISTS monthly_agg (
    project TEXT NOT NULL, access TEXT NOT NULL, agent TEXT NOT NULL,
    month TEXT NOT NULL, views INTEGER NOT NULL,
    PRIMARY KEY (project, access, agent, month)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS agg_cov (
    project TEXT NOT NULL, access TEXT NOT NULL, agent TEXT NOT NULL,
    start TEXT NOT NULL, end TEXT NOT NULL, fetched_at REAL NOT NULL, status INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at REAL NOT NULL
);
"""


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _s(d: date) -> str:
    return d.strftime("%Y%m%d")


class Cache:
    def __init__(self, path: Path | None = None, today: date | None = None):
        self.path = Path(path) if path else config.cache_dir() / "cache.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.today = today or datetime.now(timezone.utc).date()
        self.hits = 0
        self.misses = 0

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # ---------------- daily per-article views ----------------
    def _stale_cutoff_day(self) -> str:
        return _s(self.today - timedelta(days=config.RECENT_DAYS))

    def missing_range(
        self, project: str, article: str, start: str, end: str, access: str = "all-access", agent: str = "user"
    ) -> tuple[str, str] | None:
        """Smallest [start, end] sub-range that still has to be fetched, or None."""
        rows = self.conn.execute(
            "SELECT start, end, fetched_at FROM daily_cov WHERE project=? AND article=? AND access=? AND agent=?",
            (project, article, access, agent),
        ).fetchall()
        stale_before = time.time() - config.STALE_AFTER_HOURS * 3600
        recent_cut = self._stale_cutoff_day()
        covered: set[str] = set()
        for s, e, fetched_at in rows:
            d, de = _d(s), _d(e)
            while d <= de:
                ds = _s(d)
                # recent days fetched long ago may have been incomplete -> refetch
                if not (ds >= recent_cut and fetched_at < stale_before):
                    covered.add(ds)
                d += timedelta(days=1)
        need = []
        d, de = _d(start), _d(end)
        while d <= de:
            if _s(d) not in covered:
                need.append(_s(d))
            d += timedelta(days=1)
        if not need:
            self.hits += 1
            return None
        self.misses += 1
        return need[0], need[-1]

    def store_daily(
        self,
        project: str,
        article: str,
        start: str,
        end: str,
        values: dict[str, int],
        access: str = "all-access",
        agent: str = "user",
    ) -> None:
        """Store a fetched range. Days of the range absent from `values` are stored as 0."""
        d, de = _d(start), _d(end)
        rows = []
        while d <= de:
            ds = _s(d)
            rows.append((project, article, access, agent, ds, int(values.get(ds, 0))))
            d += timedelta(days=1)
        self.conn.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?)", rows)
        self.conn.execute(
            "INSERT INTO daily_cov VALUES (?,?,?,?,?,?,?)", (project, article, access, agent, start, end, time.time())
        )
        self.conn.commit()

    def get_daily(
        self, project: str, article: str, start: str, end: str, access: str = "all-access", agent: str = "user"
    ) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT day, views FROM daily WHERE project=? AND article=? AND access=? AND agent=? AND day BETWEEN ? AND ?",
            (project, article, access, agent, start, end),
        ).fetchall()
        return {d: v for d, v in rows}

    # ---------------- monthly aggregate per project ----------------
    def get_monthly_agg(
        self, project: str, months: Iterable[str], access: str = "all-access", agent: str = "user"
    ) -> dict[str, int]:
        months = list(months)
        rows = self.conn.execute(
            "SELECT month, views FROM monthly_agg WHERE project=? AND access=? AND agent=? AND month BETWEEN ? AND ?",
            (project, access, agent, months[0], months[-1]),
        ).fetchall()
        return {m: v for m, v in rows if m in set(months)}

    def store_monthly_agg(
        self, project: str, values: dict[str, int], start: str, end: str, status: int = 200,
        access: str = "all-access", agent: str = "user",
    ) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO monthly_agg VALUES (?,?,?,?,?)",
            [(project, access, agent, m, int(v)) for m, v in values.items()],
        )
        self.conn.execute(
            "INSERT INTO agg_cov VALUES (?,?,?,?,?,?,?)", (project, access, agent, start, end, time.time(), status)
        )
        self.conn.commit()

    def agg_known_missing(self, project: str, access: str = "all-access", agent: str = "user") -> bool:
        """True if the project was previously answered with 404 (no such wiki)."""
        row = self.conn.execute(
            "SELECT status FROM agg_cov WHERE project=? AND access=? AND agent=? ORDER BY fetched_at DESC LIMIT 1",
            (project, access, agent),
        ).fetchone()
        return bool(row and row[0] == 404)

    # ---------------- key/value (Wikidata, redirects) ----------------
    def kv_get(self, key: str, ttl_days: float = config.RESOLVE_TTL_DAYS):
        row = self.conn.execute("SELECT value, fetched_at FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        value, fetched_at = row
        if time.time() - fetched_at > ttl_days * 86400:
            return None
        return json.loads(value)

    def kv_set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv VALUES (?,?,?)", (key, json.dumps(value, ensure_ascii=False), time.time())
        )
        self.conn.commit()
