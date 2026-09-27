"""Month windows and period parsing.

The agent should never compute dates itself: it passes "--period 24m" (or
explicit --start/--end months) and this module turns that into the last N
*complete* months for which Wikimedia has already published data.
"""

from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import config

# A UTC day is published a few hours after it ends; keep a 2-day margin.
PUBLICATION_LAG_DAYS = 2


class PeriodError(ValueError):
    pass


def utc_today() -> date:
    """Today in UTC. WIKI_RESEARCH_TODAY=YYYY-MM-DD pins it (tests, reproducible reruns)."""
    pinned = os.environ.get("WIKI_RESEARCH_TODAY")
    if pinned:
        return date.fromisoformat(pinned)
    return datetime.now(timezone.utc).date()


def month_add(ym: tuple[int, int], k: int) -> tuple[int, int]:
    y, m = ym
    idx = y * 12 + (m - 1) + k
    return idx // 12, idx % 12 + 1


def months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] * 12 + end[1]) - (start[0] * 12 + start[1]) + 1


def ym_str(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def parse_ym(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{4})-?(\d{1,2})\s*", text)
    if not m or not (1 <= int(m.group(2)) <= 12):
        raise PeriodError(f"Month must look like 2024-09, got {text!r}")
    return int(m.group(1)), int(m.group(2))


def last_complete_month(today: date | None = None) -> tuple[int, int]:
    today = today or utc_today()
    available_until = today - timedelta(days=PUBLICATION_LAG_DAYS)
    last_day = calendar.monthrange(available_until.year, available_until.month)[1]
    if available_until.day == last_day:
        return available_until.year, available_until.month
    return month_add((available_until.year, available_until.month), -1)


def parse_period(text: str) -> int:
    """'24m' -> 24, '2y' -> 24, '36' -> 36, '18 months' -> 18."""
    t = text.strip().lower()
    m = re.fullmatch(r"(\d+)\s*(m|mo|mon|month|months|y|yr|year|years)?", t)
    if not m:
        raise PeriodError(f"Period must look like 24m or 2y, got {text!r}")
    n = int(m.group(1))
    unit = m.group(2) or "m"
    months = n * 12 if unit.startswith("y") else n
    if months < 3:
        raise PeriodError("Period must be at least 3 months (24m or more is recommended).")
    return months


@dataclass(frozen=True)
class Window:
    start: tuple[int, int]
    end: tuple[int, int]

    @property
    def n_months(self) -> int:
        return months_between(self.start, self.end)

    @property
    def months(self) -> list[str]:
        return [ym_str(month_add(self.start, i)) for i in range(self.n_months)]

    @property
    def start_day(self) -> str:
        return f"{self.start[0]:04d}{self.start[1]:02d}01"

    @property
    def end_day(self) -> str:
        last = calendar.monthrange(*self.end)[1]
        return f"{self.end[0]:04d}{self.end[1]:02d}{last:02d}"

    def days(self) -> list[str]:
        d0 = date(self.start[0], self.start[1], 1)
        d1 = date(self.end[0], self.end[1], calendar.monthrange(*self.end)[1])
        return [(d0 + timedelta(days=i)).strftime("%Y%m%d") for i in range((d1 - d0).days + 1)]

    def label(self) -> str:
        return f"{ym_str(self.start)}..{ym_str(self.end)}"


def make_window(
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    today: date | None = None,
) -> Window:
    last = last_complete_month(today)
    end_ym = parse_ym(end) if end else last
    if end_ym > last:
        raise PeriodError(
            f"End month {ym_str(end_ym)} is not complete/published yet; latest usable month is {ym_str(last)}."
        )
    if start:
        start_ym = parse_ym(start)
    else:
        n = parse_period(period or "24m")
        start_ym = month_add(end_ym, -(n - 1))
    first = parse_ym(config.FIRST_DATA_DAY[:6])
    if start_ym < first:
        raise PeriodError(f"Pageviews data starts in {ym_str(first)}; start month {ym_str(start_ym)} is too early.")
    if months_between(start_ym, end_ym) < 3:
        raise PeriodError("The window must contain at least 3 complete months.")
    return Window(start_ym, end_ym)
