"""Verify that numbers and direction claims in agent-written text match a run.

Cheap models sometimes invent or mis-round numbers. `wiki.py check` and
`wiki.py report` extract every number from the text and compare it with the
facts in summary.json (with rounding tolerance). Unknown numbers are errors;
direction words that contradict the verdicts are warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NUM_RE = re.compile(
    r"(?<![\w.,])"
    r"(?P<sign>[+\-−–])?"
    r"(?P<num>\d{1,3}(?:[ ,  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<suffix>\s?(?:%|п\.?\s?п\.?|pp|тис\.?|k\b|K\b|thousand|млн\.?|(?-i:M)\b|million|x\b|×|разів|рази))?",  # "24m" = months, not million
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(19|20)\d{2}[-./](0?[1-9]|1[0-2])([-./]\d{1,2})?\b")
QID_RE = re.compile(r"\bQ\d+\b")
NOISE_RE = re.compile(r"(https?://\S+|`[^`]*`|(?:~|\.)?/[\w./-]+|\b[\w.-]+/[\w.-]+/[\w./-]+|\b\d{8}-\d{6}[\w-]*)")  # urls, code, paths, run ids

GROWTH_WORDS = ("grow", "increas", "rising", "rise ", "rises", "зроста", "збільш", "росте", "ріст", "підйом", "приріст")
DECLINE_WORDS = ("declin", "decreas", "falling", "fell", "drop", "shrink", "спада", "падає", "падін", "зменш", "скороч", "знижен", "впав", "впала")
NEGATIONS = ("не ", "not ", "no ", "ні ", "без ", "n't ")


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_number(raw: str) -> float:
    s = raw.replace(" ", " ").replace(" ", " ")
    grouped = re.fullmatch(r"(\d{1,3}(?:[ ,]\d{3})+)(?:[.,](\d+))?", s)
    if grouped:  # "1,234" / "1 234" / "1 234,5"
        whole = re.sub(r"[ ,]", "", grouped.group(1))
        dec = grouped.group(2)
        return float(whole + ("." + dec if dec else ""))
    return float(s.replace(",", ".").replace(" ", ""))  # "12,5" decimal comma


def collect_facts(summary: dict) -> dict[str, list[float]]:
    """Numbers the text may legitimately use: 'pct' (percent values) and 'abs' (plain)."""
    pct: list[float] = []
    abs_: list[float] = []

    def add_pct(x):
        if x is not None:
            pct.append(abs(float(x)) * 100)

    for info in summary.get("analysis", {}).get("languages", {}).values():
        if info.get("status") != "ok":
            continue
        m = info["metrics"]
        abs_.append(m["avg_monthly_views_recent"])
        abs_.append(m["avg_monthly_views_recent"] * 12)
        add_pct(m.get("views_change"))
        add_pct(m.get("share_change"))
        add_pct(m.get("share_change_without_spikes"))
        add_pct(m.get("spike_share"))
        if m.get("share_per_million_recent") is not None:
            abs_.append(m["share_per_million_recent"])
        t = m.get("trend") or {}
        if t.get("slope_pct_per_year") is not None:
            pct.append(abs(t["slope_pct_per_year"]))
        if t.get("p") is not None:
            abs_.append(t["p"])
        cons = m.get("consistency")
        if cons:
            abs_ += [cons["months_up"], cons["of"]]
        for s in info.get("spikes", []):
            abs_ += [s["views"], s["typical"]]
        for c in info.get("per_concept", {}).values():
            abs_.append(c["avg_monthly_views_recent"])
            abs_.append(c["avg_monthly_views_recent"] * 12)
            add_pct(c.get("views_change"))
            add_pct(c.get("share_change"))
        season = info.get("seasonality") or {}
        if season.get("ratio"):
            abs_.append(season["ratio"])
        views = info.get("monthly", {}).get("views", [])
        if views:
            abs_ += [max(views), min(views), sum(views)]
            k = info.get("comparison", {}).get("k", 12)
            abs_ += [sum(views[-k:]), sum(views[-2 * k : -k])]
    for r in summary.get("analysis", {}).get("ranking", []):
        abs_.append(r["score"])
        abs_.append(r["score"] * 100)
    win = summary.get("analysis", {}).get("window", {})
    if win.get("months"):
        abs_.append(win["months"])
    return {"pct": pct, "abs": abs_}


def _close(value: float, candidates: list[float], pct: bool) -> bool:
    for c in candidates:
        if pct:
            if abs(value - c) <= max(1.0, 0.03 * c):
                return True
        else:
            if abs(value - c) <= max(0.5, 0.03 * abs(c)):
                return True
            # rounded to a leading digit (~1,200 for 1,183; ~600 for 559)
            mag = 10 ** max(0, len(str(int(abs(c)))) - 2)
            if abs(value - c) <= mag * 0.6:
                return True
    return False


def _nearest(value: float, candidates: list[float]) -> str:
    if not candidates:
        return ""
    best = min(candidates, key=lambda c: abs(c - value))
    return f"{best:,.1f}"


def check_text(text: str, summary: dict) -> CheckResult:
    res = CheckResult()
    facts = collect_facts(summary)
    cleaned = NOISE_RE.sub(" ", text)
    cleaned = DATE_RE.sub(" ", cleaned)
    cleaned = QID_RE.sub(" ", cleaned)
    for m in NUM_RE.finditer(cleaned):
        raw = m.group("num")
        suffix = (m.group("suffix") or "").strip().lower()
        try:
            value = _parse_number(raw)
        except ValueError:
            continue
        is_pct = suffix.startswith("%") or suffix.startswith("п") or suffix == "pp"
        if suffix in ("x", "×", "разів", "рази"):
            continue  # ratios are free-form comparisons
        if suffix.startswith("тис") or suffix in ("k", "thousand"):
            value *= 1000
        elif suffix.startswith("млн") or suffix in ("m", "million"):
            value *= 1_000_000
        if not is_pct:
            if value < 100 and not suffix:
                continue  # small counts: months, ranks, number of languages
            if 1900 <= value <= 2100 and not suffix and "," not in raw and " " not in raw:
                continue  # years
        res.checked += 1
        pool = facts["pct"] if is_pct else facts["abs"]
        if not _close(value, pool, is_pct):
            shown = raw + (("%" if is_pct else "") if suffix.startswith("%") else (" " + suffix if suffix else ""))
            hint = _nearest(value, pool)
            res.errors.append(
                f"'{shown.strip()}' is not in the analysis results"
                + (f" (nearest known value: {hint}{'%' if is_pct else ''})" if hint else "")
                + ". Use numbers exactly as printed by `wiki.py research`."
            )

    directions = {i.get("direction") for i in summary.get("analysis", {}).get("languages", {}).values()}
    low = " " + text.lower()

    def mentions(words) -> bool:
        for w in words:
            for mm in re.finditer(re.escape(w), low):
                before = low[max(0, mm.start() - 12) : mm.start()]
                if not any(n in before for n in NEGATIONS):
                    return True
        return False

    if mentions(GROWTH_WORDS) and "growing" not in directions and "mixed" not in directions:
        res.warnings.append("Text talks about growth, but no language has direction 'growing' in this run.")
    if mentions(DECLINE_WORDS) and "declining" not in directions and "mixed" not in directions:
        res.warnings.append("Text talks about decline, but no language has direction 'declining' in this run.")
    return res
