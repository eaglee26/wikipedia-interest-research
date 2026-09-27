"""The `research` pipeline: resolve -> fetch -> analyse -> save run -> summary."""

from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import analyze, charts, config, languages, runs
from .cache import Cache
from .dates import Window, make_window, utc_today
from .fetch import FetchReport, fetch_daily, fetch_monthly_totals
from .net import HttpClient, HttpError, NetworkBlocked
from .resolve import ResolveError, broader_concepts, fetch_redirects, resolve_topics


class UsageError(Exception):
    """Bad input the agent can fix (message says how)."""


@dataclass
class ResearchParams:
    topics: list[str]
    langs: list[str]
    qids: list[str] = field(default_factory=list)
    period: str | None = None
    start: str | None = None
    end: str | None = None
    search_lang: str | None = None
    weights: dict = field(default_factory=dict)
    exclude: list[str] = field(default_factory=list)
    redirects: str = "auto"
    ui: str = "en"
    out_dir: Path = field(default_factory=config.default_out_dir)
    offline: bool = False
    charts: bool = True
    run_id: str | None = None


def parse_weights(text: str | None) -> dict:
    if not text:
        return {}
    out = {}
    for part in text.replace(";", ",").split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise UsageError(f"--weights must look like growth=0.5,volume=0.3,reliability=0.2 (got {text!r})")
        k, v = part.split("=", 1)
        k = k.strip().lower()
        aliases = {"stability": "reliability", "confidence": "reliability", "size": "volume", "audience": "volume"}
        k = aliases.get(k, k)
        if k not in config.DEFAULT_WEIGHTS:
            raise UsageError(f"Unknown weight '{k}'. Use volume, growth, reliability.")
        try:
            out[k] = float(v)
        except ValueError as e:
            raise UsageError(f"Weight for {k} must be a number, got {v!r}") from e
    return out


def _offline_transport(url: str, headers: dict, timeout: float):
    raise NetworkBlocked(f"offline mode: {url} is not in the cache", url=url)


def _first_nonzero_month(series: dict[str, int], window: Window) -> int | None:
    days = sorted(d for d, v in series.items() if v > 0)
    if not days:
        return None
    first = days[0]
    return window.months.index(f"{first[:4]}-{first[4:6]}")


def run_research(p: ResearchParams, client: HttpClient | None = None, cache: Cache | None = None) -> tuple[dict, Path]:
    lc = languages.normalize_langs(p.langs)
    if lc.errors:
        raise UsageError(" ".join(lc.errors))
    langs = lc.codes
    if len(langs) > 12:
        raise UsageError("At most 12 languages per run (split the question into several runs).")
    try:
        window = make_window(p.period, p.start, p.end)
    except ValueError as e:
        raise UsageError(str(e)) from e
    topics = p.topics
    if not topics and not p.qids:
        raise UsageError("Pass --topics (names, any language) or --qids (Wikidata ids).")
    if len(topics) + len(p.qids) > 10:
        raise UsageError("At most 10 topics per run; pick the 3-7 most representative articles.")

    client = client or HttpClient(transport=_offline_transport if p.offline else None)
    cache = cache or Cache(today=utc_today())
    notes = list(lc.notes)

    concepts, rnotes = resolve_topics(client, cache, topics, langs, p.search_lang, p.qids)
    notes += rnotes
    if p.exclude:
        ex = {e.strip().casefold() for e in p.exclude if e.strip()}
        kept = [c for c in concepts if not ({c.qid.casefold(), c.label.casefold(), c.query.casefold()} & ex)]
        if len(kept) < len(concepts):
            notes.append(f"Excluded: {', '.join(c.label for c in concepts if c not in kept)}")
        concepts = kept
        if not concepts:
            raise UsageError("--exclude removed every topic.")

    proxies: dict[str, list[dict]] = {}
    for c in concepts:
        if any(not c.titles.get(lang) for lang in langs):
            try:
                existing = {x.qid for x in concepts}
                proxies[c.qid] = [p for p in broader_concepts(client, cache, c.qid, langs) if p["qid"] not in existing]
            except (HttpError, ResolveError):
                proxies[c.qid] = []

    try:
        totals = fetch_monthly_totals(client, cache, langs, window)
    except Exception as e:  # UnknownWiki and network errors carry actionable messages
        if e.__class__.__name__ == "UnknownWiki":
            raise UsageError(str(e)) from e
        raise

    report = FetchReport()
    jobs = [(lang, c.titles[lang]) for c in concepts for lang in langs if c.titles.get(lang)]
    series = fetch_daily(client, cache, jobs, window, report)

    # ---- redirects: recover views of renamed articles (auto) or all alias titles (all)
    redirects_used: dict[tuple[str, str], list[str]] = {}
    if p.redirects != "none" and jobs:
        wanted: dict[str, list[str]] = {}
        for lang, title in jobs:
            first = _first_nonzero_month(series[(lang, title)], window)
            late = first is None or first >= config.THRESHOLDS["late_start_months"]
            if p.redirects == "all" or late:
                wanted.setdefault(lang, []).append(title)
        for lang, titles in wanted.items():
            reds = fetch_redirects(client, cache, lang, titles)
            extra = [(lang, r) for t in titles for r in reds.get(t, [])]
            if extra:
                extra_series = fetch_daily(client, cache, extra, window, report)
                for t in titles:
                    used = [r for r in reds.get(t, []) if sum(extra_series[(lang, r)].values()) > 0]
                    if used:
                        redirects_used[(lang, t)] = used
                        for r in used:
                            for d, v in extra_series[(lang, r)].items():
                                series[(lang, t)][d] += v

    days = window.days()
    daily_arrays: dict[tuple[str, str], np.ndarray] = {}
    for c in concepts:
        for lang in langs:
            t = c.titles.get(lang)
            if t:
                s = series[(lang, t)]
                daily_arrays[(lang, c.qid)] = np.array([s.get(d, 0) for d in days], dtype=float)

    analysis = analyze.build_analysis(window, concepts, langs, daily_arrays, totals, p.weights)

    run_id = p.run_id or runs.new_run_id([c.label for c in concepts], langs)
    run_path = runs.runs_root(p.out_dir) / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    first_lang = next((l for l in langs if analysis["languages"][l].get("status") == "ok"), None)
    comp = analysis["languages"][first_lang]["comparison"] if first_lang else {"kind": "yoy12", "k": 12}
    summary = {
        "run_id": run_id,
        "run_path": str(run_path),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skill_version": config.VERSION,
        "params": {
            "topics": topics,
            "qids": p.qids,
            "langs": langs,
            "period": p.period,
            "start": p.start,
            "end": p.end,
            "weights": {**config.DEFAULT_WEIGHTS, **p.weights},
            "exclude": p.exclude,
            "redirects": p.redirects,
            "ui": p.ui,
            "access": "all-access",
            "agent": "user",
        },
        "window": {
            "start": window.months[0],
            "end": window.months[-1],
            "months": window.n_months,
            "months_list": window.months,
        },
        "comparison_text_ui": {
            ui: analyze.comparison_text(comp["kind"], comp["k"], ui) for ui in ("en", "uk")
        },
        "concepts": [c.to_dict() for c in concepts],
        "redirects_used": {f"{l}:{t}": r for (l, t), r in redirects_used.items()},
        "proxies": proxies,
        "notes": notes,
        "analysis": analysis,
        "fetch": {
            "http_requests": client.stats.requests,
            "retries": client.stats.retries,
            "series_from_cache": report.from_cache,
            "series_fetched": report.requested,
        },
        "files": {},
    }
    analysis["window"]["months_list"] = window.months
    analysis["comparison_text_ui"] = summary["comparison_text_ui"]

    _write_csv(run_path / "data_monthly.csv", window, concepts, langs, analysis)
    summary["files"]["data"] = "data_monthly.csv"
    if p.charts:
        charts.ensure_mpl_cache()
        t = charts.save_trend_png(analysis, run_path / "trend.png", p.ui)
        g = charts.save_growth_png(analysis, run_path / "growth.png", p.ui)
        if t:
            summary["files"]["trend_chart"] = "trend.png"
        if g:
            summary["files"]["growth_chart"] = "growth.png"
    summary["files"]["summary"] = "summary.json"
    (run_path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    runs.append_index(p.out_dir, runs.index_entry(summary))
    cache.close()
    return summary, run_path


def _write_csv(path: Path, window: Window, concepts, langs: list[str], analysis: dict) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lang", "month", "item", "qid", "title", "views", "edition_total_views", "views_per_million"])
        for lang in langs:
            info = analysis["languages"][lang]
            if info.get("status") != "ok":
                continue
            totals = info["monthly"]["totals"]
            for i, m in enumerate(window.months):
                tot = totals[i]
                v = info["monthly"]["views"][i]
                w.writerow([lang, m, "BASKET", "", "", v, tot, round(v / tot * 1e6, 3) if tot else ""])
                for q, c in info["per_concept"].items():
                    cv = c["monthly"][i]
                    w.writerow([lang, m, "concept", q, c["title"], cv, tot, round(cv / tot * 1e6, 3) if tot else ""])


def log_command(out_dir: Path, argv: list[str], status: int, run_id: str | None = None) -> None:
    """Append-only usage log (lets evals verify that the agent used the skill's CLI)."""
    try:
        d = Path(out_dir) / ".log"
        d.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "argv": argv,
            "status": status,
            "run_id": run_id,
            "pid": os.getpid(),
        }
        with (d / "commands.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        print("[warn] could not write command log", file=sys.stderr)
