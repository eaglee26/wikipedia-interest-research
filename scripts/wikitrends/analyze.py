"""Metrics, trust checks, confidence and ranking.

Design rule: every judgement a cheap model might get wrong (is this growth?
is it trustworthy? which language is more promising?) is computed here with
transparent rules, and returned together with the reasons in plain words.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from . import config, i18n, languages
from . import stats as st
from .dates import Window

T = config.THRESHOLDS


# ----------------------------------------------------------------- formatting
def fmt_pct(x: float | None, digits: int = 0) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    s = f"{x * 100:+.{digits}f}%"
    return "0%" if float(s[:-1]) == 0 else s


def fmt_int(n: float | None) -> str:
    if n is None:
        return "n/a"
    return f"{int(round(n)):,}"


def fmt_num(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x:,.{digits}f}"


@dataclass
class Flag:
    id: str
    severity: str  # critical | warn | info
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "params": self.params,
            "message": i18n.flag_text(self.id, self.params, "en"),
        }


# ----------------------------------------------------------------- helpers
def _comparison(n: int) -> tuple[str, int, list[int], list[int]]:
    """Return (kind, k, recent_idx, previous_idx) for n monthly points."""
    if n >= 24:
        k = 12
        return "yoy12", k, list(range(n - 12, n)), list(range(n - 24, n - 12))
    if n >= 13:
        k = n - 12
        return "yoyk", k, list(range(n - k, n)), list(range(n - k - 12, n - 12))
    k = n // 2
    return "halves", k, list(range(n - k, n)), list(range(0, k))


def comparison_text(kind: str, k: int, ui: str = "en") -> str:
    if kind == "yoy12":
        return i18n.label("comparison_12", ui)
    if kind == "yoyk":
        return i18n.label("comparison_k", ui, k=k)
    return i18n.label("comparison_half", ui)


def _ratio_change(num_recent: float, num_prev: float) -> float | None:
    if num_prev <= 0:
        return None
    return num_recent / num_prev - 1.0


def _share_change(v: np.ndarray, a: np.ndarray, recent: list[int], prev: list[int]) -> float | None:
    ar, ap = a[recent].sum(), a[prev].sum()
    vr, vp = v[recent].sum(), v[prev].sum()
    if ar <= 0 or ap <= 0 or vp <= 0:
        return None
    return (vr / ar) / (vp / ap) - 1.0


def _month_index(window: Window) -> dict[str, int]:
    return {m: i for i, m in enumerate(window.months)}


def _monthly(daily: np.ndarray, day_month_idx: np.ndarray, n_months: int) -> np.ndarray:
    return np.bincount(day_month_idx, weights=daily, minlength=n_months)


def load_known_issues() -> list[dict]:
    path = config.ASSETS_DIR / "known-data-issues.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


# ----------------------------------------------------------------- core
@dataclass
class SeriesMetrics:
    avg_recent: float
    views_change: float | None
    share_change: float | None
    share_pm_recent: float | None
    first_month: str | None


def _series_metrics(v: np.ndarray, a: np.ndarray, recent: list[int], prev: list[int], months: list[str]) -> SeriesMetrics:
    nz = np.nonzero(v > 0)[0]
    share_pm = None
    if a[recent].sum() > 0:
        share_pm = float(v[recent].sum() / a[recent].sum() * 1e6)
    return SeriesMetrics(
        avg_recent=float(v[recent].mean()) if recent else 0.0,
        views_change=_ratio_change(float(v[recent].sum()), float(v[prev].sum())),
        share_change=_share_change(v, a, recent, prev),
        share_pm_recent=share_pm,
        first_month=months[int(nz[0])] if len(nz) else None,
    )


def analyze_language(
    lang: str,
    window: Window,
    basket: list[str],
    concept_titles: dict[str, str],
    concept_daily: dict[str, np.ndarray],
    totals: np.ndarray,
    missing_concepts: list[str],
    concept_labels: dict[str, str],
) -> dict:
    months = window.months
    n = len(months)
    days = window.days()
    midx = _month_index(window)
    day_month = np.array([midx[f"{d[:4]}-{d[4:6]}"] for d in days])
    kind, k, recent, prev = _comparison(n)
    flags: list[Flag] = []
    info: dict = {"lang": lang, "name": languages.name(lang), "basket": basket}

    if not basket:
        flags.append(Flag("no_article", "critical", {"concepts": ", ".join(concept_labels[q] for q in missing_concepts)}))
        info.update(status="no_data", direction="no_data", confidence="NONE", flags=[f.to_dict() for f in flags])
        return info
    if missing_concepts:
        flags.append(
            Flag(
                "partial_basket",
                "info",
                {
                    "have": len(basket),
                    "total": len(basket) + len(missing_concepts),
                    "missing": ", ".join(concept_labels[q] for q in missing_concepts),
                },
            )
        )

    daily_sum = np.zeros(len(days))
    for q in basket:
        daily_sum += concept_daily[q]
    if daily_sum.sum() <= 0:
        flags.append(Flag("no_views", "critical"))
        info.update(status="no_data", direction="no_data", confidence="NONE", flags=[f.to_dict() for f in flags])
        return info
    v = _monthly(daily_sum, day_month, n)
    a = totals.astype(float)
    base = _series_metrics(v, a, recent, prev, months)
    share_monthly = np.where(a > 0, v / np.maximum(a, 1) * 1e6, 0.0)

    # ---- consistency: months beating the same month a year earlier (share)
    cons, cons_k = None, None
    if n >= 13:
        idx = [i for i in recent if i - 12 >= 0]
        cons = int(sum(1 for i in idx if share_monthly[i] > share_monthly[i - 12]))
        cons_k = len(idx)

    # ---- trend test on log share
    logs = st.safe_log(share_monthly, floor=1e-3)
    if n >= 24:
        tt = st.seasonal_kendall(logs)
        slope_year = st.seasonal_theil_sen(logs)
    else:
        tt = st.mann_kendall(logs)
        slope_year = st.theil_sen(logs)[0] * 12
    trend = {
        "test": tt.test,
        "p": round(tt.p, 4),
        "z": round(tt.z, 3),
        "slope_pct_per_year": round((math.exp(slope_year) - 1) * 100, 1),
    }

    # ---- spikes (daily basket series)
    med = st.rolling_median(daily_sum, 29)
    spike_mask = (daily_sum > np.maximum(T["spike_multiplier"] * med, med + T["spike_floor"])) & (
        daily_sum >= T["spike_floor"]
    )
    excess = np.where(spike_mask, daily_sum - med, 0.0)
    # spikes can inflate either side of the comparison: measure both periods
    spike_share = 0.0
    for period in (recent, prev):
        mask = np.isin(day_month, period)
        total = daily_sum[mask].sum()
        if total > 0:
            spike_share = max(spike_share, float(excess[mask].sum() / total))
    cleaned = np.where(spike_mask, med, daily_sum)
    v_clean = _monthly(cleaned, day_month, n)
    share_change_clean = _share_change(v_clean, a, recent, prev)
    top = np.argsort(-excess)[:3]
    spikes = [
        {"day": f"{days[i][:4]}-{days[i][4:6]}-{days[i][6:]}", "views": int(daily_sum[i]), "typical": int(round(float(med[i])))}
        for i in top
        if excess[i] > 0
    ]
    spike_month_idx = sorted({int(day_month[i]) for i in np.nonzero(spike_mask)[0]})

    # ---- per concept
    per_concept = {}
    for q in basket:
        cv = _monthly(concept_daily[q], day_month, n)
        m = _series_metrics(cv, a, recent, prev, months)
        per_concept[q] = {
            "title": concept_titles[q],
            "label": concept_labels[q],
            "avg_monthly_views_recent": round(m.avg_recent, 1),
            "views_change": None if m.views_change is None else round(m.views_change, 4),
            "share_change": None if m.share_change is None else round(m.share_change, 4),
            "first_month": m.first_month,
            "monthly": [int(x) for x in cv],
        }

    # ---- direction
    sc = base.share_change
    thr = T["change_threshold"]
    up_need = math.ceil(T["consistency_up"] * (cons_k or 12) / 12)
    down_max = math.floor(T["consistency_down"] * (cons_k or 12) / 12)
    significant = tt.p < T["mk_alpha"]
    if sc is None:
        direction = "mixed"
    elif sc >= thr and ((cons is not None and cons >= up_need) or (significant and tt.direction > 0)):
        direction = "growing"
    elif sc <= -thr and ((cons is not None and cons <= down_max) or (significant and tt.direction < 0)):
        direction = "declining"
    elif abs(sc) < thr:
        direction = "stable"
    else:
        direction = "mixed"

    # ---- trust checks
    avg = base.avg_recent
    if avg < T["volume_critical"]:
        flags.append(Flag("volume_critical", "critical", {"avg": fmt_int(avg)}))
    elif avg < T["volume_warn"]:
        flags.append(Flag("volume_warn", "warn", {"avg": fmt_int(avg)}))

    if n < 13:
        flags.append(Flag("too_short", "critical", {"n": n}))
    elif n < 24:
        flags.append(Flag("short_window", "warn", {"k": k}))

    spike_driven = False
    if sc is not None and share_change_clean is not None and abs(sc) >= thr:
        flipped = (sc > 0) != (share_change_clean > 0)
        shrunk = abs(share_change_clean) < 0.5 * abs(sc)
        if spike_share >= T["spike_share_warn"] and (flipped or shrunk):
            spike_driven = True
    if spike_driven:
        flags.append(
            Flag(
                "spike_driven",
                "critical",
                {"spike_share": round(spike_share * 100), "clean": fmt_pct(share_change_clean)},
            )
        )
    elif spikes:
        s0 = spikes[0]
        flags.append(Flag("spikes_present", "info", {"day": s0["day"], "views": fmt_int(s0["views"]), "typical": fmt_int(s0["typical"])}))

    late_limit = T["late_start_months"]
    recent_basket = v[recent].sum()
    for q in basket:
        fm = per_concept[q]["first_month"]
        if fm is None:
            continue
        pos = months.index(fm)
        if pos >= late_limit:
            weight = (np.array(per_concept[q]["monthly"])[recent].sum() / recent_basket) if recent_basket > 0 else 0
            sev = "critical" if weight >= 0.2 else "warn"
            flags.append(Flag("late_start", sev, {"title": concept_titles[q], "first": fm}))

    if len(basket) >= 2 and sc is not None:
        considered = [
            q for q in basket if per_concept[q]["share_change"] is not None and per_concept[q]["avg_monthly_views_recent"] >= 30
        ]
        if len(considered) >= 2:
            def same(x: float) -> bool:
                if direction == "growing":
                    return x > 0
                if direction == "declining":
                    return x < 0
                return abs(x) < thr

            k_same = sum(1 for q in considered if same(per_concept[q]["share_change"]))
            if k_same / len(considered) < T["breadth_min"]:
                flags.append(Flag("narrow", "warn", {"k": k_same, "m": len(considered)}))

    if direction in ("growing", "declining") and not significant:
        flags.append(Flag("not_significant", "warn", {"p": f"{tt.p:.2f}"}))
    if direction == "mixed" and cons is not None:
        flags.append(Flag("mixed_signals", "warn", {"change": fmt_pct(sc), "cons": cons, "k": cons_k}))

    vc = base.views_change
    if vc is not None and sc is not None:
        def cat(x: float) -> int:
            return 1 if x >= thr else (-1 if x <= -thr else 0)

        opposite = cat(vc) * cat(sc) == -1
        differs = cat(vc) != cat(sc)
        if opposite or differs or abs(vc - sc) >= T["platform_gap_pp"]:
            flags.append(
                Flag("platform_effect", "warn" if opposite else "info", {"views": fmt_pct(vc), "share": fmt_pct(sc)})
            )

    # ---- seasonality (share, calendar-month means)
    seasonality = None
    if n >= 24:
        cal = [int(m[5:7]) for m in months]
        share_clean = np.where(a > 0, v_clean / np.maximum(a, 1) * 1e6, 0.0)  # spikes removed
        means = {}
        for mo in range(1, 13):
            vals = [share_clean[i] for i in range(n) if cal[i] == mo]
            if vals:
                means[mo] = float(np.mean(vals))
        positive = [x for x in means.values() if x > 0]
        if len(positive) >= 10:
            peak = max(means, key=lambda mo: means[mo])
            ratio = means[peak] / min(positive)
            peaks = sorted(mo for mo, x in means.items() if x >= 0.85 * means[peak])
            seasonality = {"peak_months": peaks, "ratio": round(ratio, 1)}
            if ratio >= T["seasonality_ratio"]:
                flags.append(Flag("seasonality", "info", {"months": peaks, "ratio": round(ratio, 1)}))

    # ---- confidence
    crit = [f for f in flags if f.severity == "critical"]
    warns = [f for f in flags if f.severity == "warn"]
    if crit or len(warns) >= 3:
        confidence = "LOW"
    elif warns:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    info.update(
        status="ok",
        comparison={"kind": kind, "k": k, "text": comparison_text(kind, k, "en")},
        metrics={
            "avg_monthly_views_recent": round(avg, 1),
            "views_change": None if vc is None else round(vc, 4),
            "share_change": None if sc is None else round(sc, 4),
            "share_change_without_spikes": None if share_change_clean is None else round(share_change_clean, 4),
            "share_per_million_recent": None if base.share_pm_recent is None else round(base.share_pm_recent, 2),
            "consistency": None if cons is None else {"months_up": cons, "of": cons_k},
            "spike_share": round(spike_share, 4),
            "trend": trend,
        },
        direction=direction,
        confidence=confidence,
        flags=[f.to_dict() for f in flags],
        spikes=spikes,
        spike_months=[months[i] for i in spike_month_idx],
        seasonality=seasonality,
        per_concept=per_concept,
        monthly={
            "views": [int(x) for x in v],
            "totals": [int(x) for x in a],
            "share_pm": [round(float(x), 3) for x in share_monthly],
        },
    )
    return info


def rank_languages(lang_infos: dict[str, dict], weights: dict[str, float]) -> list[dict]:
    ok = {l: i for l, i in lang_infos.items() if i.get("status") == "ok"}
    if not ok:
        return []
    vols = {l: math.log10(max(i["metrics"]["avg_monthly_views_recent"], 1.0)) for l, i in ok.items()}
    grow = {l: (i["metrics"]["share_change"] if i["metrics"]["share_change"] is not None else 0.0) for l, i in ok.items()}
    rel = {l: config.CONFIDENCE_SCORE.get(i["confidence"], 0.2) for l, i in ok.items()}

    def norm(d: dict[str, float]) -> dict[str, float]:
        lo, hi = min(d.values()), max(d.values())
        if hi - lo < 1e-12:
            return {k: 0.5 for k in d}
        return {k: (x - lo) / (hi - lo) for k, x in d.items()}

    nv, ng = norm(vols), norm(grow)
    w = {**config.DEFAULT_WEIGHTS, **(weights or {})}
    total_w = sum(w.values()) or 1.0
    rows = []
    for l in ok:
        score = (w["volume"] * nv[l] + w["growth"] * ng[l] + w["reliability"] * rel[l]) / total_w
        rows.append({"lang": l, "score": round(score, 3)})
    rows.sort(key=lambda r: -r["score"])
    best_vol = max(ok, key=lambda l: vols[l])
    best_grow = max(ok, key=lambda l: grow[l])
    for rank, r in enumerate(rows, 1):
        l = r["lang"]
        i = ok[l]
        reasons = []
        if l == best_vol and len(ok) > 1:
            reasons.append("largest audience")
        if l == best_grow and len(ok) > 1 and grow[l] >= T["change_threshold"]:
            reasons.append("fastest growth")
        reasons.append(f"{fmt_int(i['metrics']['avg_monthly_views_recent'])} views/month")
        reasons.append(f"share {fmt_pct(i['metrics']['share_change'])}")
        reasons.append(f"{i['confidence']} confidence")
        r.update(rank=rank, why="; ".join(reasons))
    return rows


def build_analysis(
    window: Window,
    concepts: list,  # list[resolve.Concept]
    langs: list[str],
    daily: dict[tuple[str, str], np.ndarray],  # (lang, qid) -> daily array aligned to window.days()
    totals: dict[str, dict[str, int]],
    weights: dict[str, float] | None = None,
) -> dict:
    labels = {c.qid: c.label for c in concepts}
    available = {lang: [c.qid for c in concepts if c.titles.get(lang)] for lang in langs}
    with_data = [l for l in langs if available[l]]
    common = [c.qid for c in concepts if all(c.titles.get(l) for l in with_data)] if with_data else []
    like_for_like = bool(common) or len(with_data) <= 1
    use_common = len(with_data) >= 2 and bool(common)

    lang_infos = {}
    for lang in langs:
        basket = common if use_common else available[lang]
        missing = [c.qid for c in concepts if not c.titles.get(lang)]
        titles = {c.qid: c.titles.get(lang) for c in concepts if c.titles.get(lang)}
        tot = np.array([totals.get(lang, {}).get(m, 0) for m in window.months], dtype=float)
        info = analyze_language(
            lang,
            window,
            basket,
            titles,
            {q: daily[(lang, q)] for q in basket},
            tot,
            missing,
            labels,
        )
        if use_common:
            info["excluded_from_comparison"] = [q for q in available[lang] if q not in common]
        lang_infos[lang] = info

    notes = []
    if not like_for_like:
        notes.append(Flag("not_like_for_like", "warn").to_dict())
    issues = []
    for issue in load_known_issues():
        if issue["start"] <= window.months[-1] and issue["end"] >= window.months[0]:
            issues.append(issue)

    return {
        "window": {"start": window.months[0], "end": window.months[-1], "months": window.n_months},
        "basket_mode": "common" if use_common else "per-language",
        "common_concepts": common,
        "languages": lang_infos,
        "ranking": rank_languages(lang_infos, weights or {}),
        "weights": {**config.DEFAULT_WEIGHTS, **(weights or {})},
        "global_flags": notes,
        "known_issues": issues,
        "thresholds": dict(T),
    }
