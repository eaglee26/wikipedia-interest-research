"""Fetch pageviews (per article, daily) and project totals (monthly) with caching."""

from __future__ import annotations

import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import config, languages
from .cache import Cache
from .dates import Window
from .net import HttpClient, NotFound

ACCESS = "all-access"
AGENT = "user"


class UnknownWiki(Exception):
    pass


def _article_key(title: str) -> str:
    return title.replace(" ", "_")


def per_article_url(lang: str, title: str, start: str, end: str, granularity: str = "daily") -> str:
    art = urllib.parse.quote(_article_key(title), safe="")
    return f"{config.PAGEVIEWS_BASE}/per-article/{languages.project(lang)}/{ACCESS}/{AGENT}/{art}/{granularity}/{start}/{end}"


def aggregate_url(lang: str, start: str, end: str) -> str:
    return f"{config.PAGEVIEWS_BASE}/aggregate/{languages.project(lang)}/{ACCESS}/{AGENT}/monthly/{start}/{end}"


def _fetch_article(client: HttpClient, lang: str, title: str, start: str, end: str) -> tuple[dict[str, int], int]:
    try:
        data = client.get_json(per_article_url(lang, title, start, end))
    except NotFound:
        return {}, 404
    values: dict[str, int] = {}
    for item in data.get("items", []):
        values[str(item["timestamp"])[:8]] = int(item.get("views", 0))
    return values, 200


@dataclass
class FetchReport:
    requested: int = 0
    from_cache: int = 0
    no_data: int = 0


def fetch_daily(
    client: HttpClient,
    cache: Cache,
    jobs: list[tuple[str, str]],
    window: Window,
    report: FetchReport | None = None,
    quiet: bool = False,
) -> dict[tuple[str, str], dict[str, int]]:
    """(lang, title) -> {YYYYMMDD: views} covering every day of the window."""
    report = report or FetchReport()
    start, end = window.start_day, window.end_day
    todo: list[tuple[str, str, str, str]] = []
    for lang, title in dict.fromkeys(jobs):
        rng = cache.missing_range(languages.project(lang), _article_key(title), start, end, ACCESS, AGENT)
        if rng is None:
            report.from_cache += 1
        else:
            todo.append((lang, title, rng[0], rng[1]))
    if todo and not quiet:
        print(f"[fetch] {len(todo)} article series from Wikimedia ({report.from_cache} cached)...", file=sys.stderr)
    if todo:
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            futures = [(job, pool.submit(_fetch_article, client, job[0], job[1], job[2], job[3])) for job in todo]
            for (lang, title, s, e), fut in futures:
                values, status = fut.result()
                report.requested += 1
                if status == 404:
                    report.no_data += 1
                cache.store_daily(languages.project(lang), _article_key(title), s, e, values, ACCESS, AGENT)
    out: dict[tuple[str, str], dict[str, int]] = {}
    days = window.days()
    for lang, title in dict.fromkeys(jobs):
        stored = cache.get_daily(languages.project(lang), _article_key(title), start, end, ACCESS, AGENT)
        out[(lang, title)] = {d: stored.get(d, 0) for d in days}
    return out


def fetch_monthly_totals(
    client: HttpClient, cache: Cache, langs: list[str], window: Window, quiet: bool = False
) -> dict[str, dict[str, int]]:
    """lang -> {YYYY-MM: total user views of that Wikipedia}. Raises UnknownWiki."""
    months = window.months
    out: dict[str, dict[str, int]] = {}
    todo: list[tuple[str, str, str]] = []
    for lang in langs:
        proj = languages.project(lang)
        have = cache.get_monthly_agg(proj, months, ACCESS, AGENT)
        missing = [m for m in months if m not in have]
        if not missing:
            out[lang] = have
            continue
        first, last = missing[0], missing[-1]
        s = first.replace("-", "") + "01"
        # last day of the last missing month
        e = window.end_day if last == months[-1] else _month_end(last)
        todo.append((lang, s, e))
    if todo and not quiet:
        print(f"[fetch] totals for {len(todo)} Wikipedia edition(s)...", file=sys.stderr)

    def job(lang: str, s: str, e: str):
        try:
            return client.get_json(aggregate_url(lang, s, e)), 200
        except NotFound:
            return {}, 404

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = [((lang, s, e), pool.submit(job, lang, s, e)) for lang, s, e in todo]
        for (lang, s, e), fut in futures:
            data, status = fut.result()
            proj = languages.project(lang)
            if status == 404:
                cache.store_monthly_agg(proj, {}, s, e, status=404, access=ACCESS, agent=AGENT)
                raise UnknownWiki(
                    f"No Wikipedia edition with code '{lang}' (the Pageviews API has no totals for {proj}). "
                    "Check the language code."
                )
            values = {}
            for item in data.get("items", []):
                ts = str(item["timestamp"])
                values[f"{ts[:4]}-{ts[4:6]}"] = int(item.get("views", 0))
            cache.store_monthly_agg(proj, values, s, e, status=200, access=ACCESS, agent=AGENT)
    for lang in langs:
        if lang not in out:
            out[lang] = cache.get_monthly_agg(languages.project(lang), months, ACCESS, AGENT)
    return out


def _month_end(ym: str) -> str:
    import calendar

    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y:04d}{m:02d}{calendar.monthrange(y, m)[1]:02d}"


def monthly_from_daily(daily: dict[str, int], months: list[str]) -> list[int]:
    sums = {m: 0 for m in months}
    for d, v in daily.items():
        key = f"{d[:4]}-{d[4:6]}"
        if key in sums:
            sums[key] += v
    return [sums[m] for m in months]
