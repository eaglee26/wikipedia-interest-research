"""Static charts (matplotlib, Agg backend) for PNG files and the PDF report.

Colour rules follow a validated categorical palette (fixed slot order, checked
for colour-vision deficiency); every series also gets a direct end label and
the PDF carries a numbers table, so identity never relies on colour alone.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import i18n, languages  # noqa: E402

# Validated categorical palette (light surface), fixed order - never cycled.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SURFACE = "#ffffff"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#8a8985"
GRID = "#e6e5e1"
BAND = "#f0efec"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",  # bundled with matplotlib; covers Cyrillic and CE diacritics
        "font.size": 8,
        "axes.edgecolor": GRID,
        "axes.labelcolor": TEXT_2,
        "axes.titlesize": 9,
        "axes.titleweight": "bold",
        "axes.titlecolor": TEXT,
        "xtick.color": TEXT_2,
        "ytick.color": TEXT_2,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "xtick.minor.size": 0,
        "ytick.minor.size": 0,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,  # embed TrueType so text stays selectable/searchable in the PDF
        "savefig.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
    }
)


def color_for(index: int) -> str:
    return SERIES[index % len(SERIES)] if index < len(SERIES) else "#9a9893"


def _thousands(x: float, _pos=None) -> str:
    if x >= 1000:
        return f"{x:,.0f}"
    if x >= 10:
        return f"{x:.0f}"
    return f"{x:g}"


def _style(ax) -> None:
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", labelsize=7, pad=2)


def _month_ticks(ax, months: list[str], ui: str) -> None:
    n = len(months)
    step = 3 if n <= 24 else (6 if n <= 60 else 12)
    idx = [i for i, m in enumerate(months) if (int(m[5:7]) - 1) % step == 0]
    ax.set_xticks(idx)
    names = i18n.MONTHS[ui if ui in i18n.MONTHS else "en"]
    ax.set_xticklabels([f"{names[int(months[i][5:7]) - 1]}\n{months[i][:4]}" for i in idx])
    ax.set_xlim(-0.5, n - 0.5)


def _known_issue_band(ax, months: list[str], issues: list[dict], ui: str, show_label: bool) -> None:
    for issue in issues:
        idx = [i for i, m in enumerate(months) if issue["start"] <= m <= issue["end"]]
        if not idx:
            continue
        ax.axvspan(idx[0] - 0.5, idx[-1] + 0.5, color=BAND, zorder=0, linewidth=0)
        if show_label:
            ax.text(
                (idx[0] + idx[-1]) / 2,
                0.97,
                i18n.label("data_issue", ui),
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                fontsize=5.5,
                color=MUTED,
                zorder=5,
                bbox={"boxstyle": "round,pad=0.15", "facecolor": BAND, "edgecolor": "none", "alpha": 0.9},
            )


def _lang_order(analysis: dict) -> list[str]:
    return [l for l, i in analysis["languages"].items() if i.get("status") == "ok"]


def draw_trend(ax_views, ax_share, analysis: dict, ui: str = "en") -> None:
    months = analysis["window"]["months_list"]
    langs = _lang_order(analysis)
    all_langs = list(analysis["languages"])
    issues = analysis.get("known_issues", [])
    x = list(range(len(months)))
    for ax, key, title in (
        (ax_views, "views", i18n.label("chart_views", ui)),
        (ax_share, "share_pm", i18n.label("chart_share", ui)),
    ):
        if ax is None:
            continue
        _style(ax)
        _known_issue_band(ax, months, issues, ui, show_label=(ax is ax_views or ax_views is None))
        maxima, minima = [], []
        end_labels: list[tuple[str, float, float]] = []
        for lang in langs:
            info = analysis["languages"][lang]
            ys = info["monthly"][key]
            c = color_for(all_langs.index(lang))
            ax.plot(x, ys, color=c, linewidth=1.8, solid_joinstyle="round", solid_capstyle="round", label=lang, zorder=3)
            ax.plot([x[-1]], [ys[-1]], "o", color=c, markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
            end_labels.append((lang, x[-1], ys[-1]))
            spikes = set(info.get("spike_months", []))
            sx = [i for i, m in enumerate(months) if m in spikes]
            if sx:
                ax.plot(sx, [ys[i] for i in sx], "^", color=c, markersize=5, markeredgecolor=SURFACE, markeredgewidth=0.8, zorder=4)
            positive = [y for y in ys if y > 0]
            if positive:
                maxima.append(max(positive))
                minima.append(min(positive))
        if maxima and max(maxima) / max(min(minima), 1e-9) > 25:
            ax.set_yscale("log")
        else:
            ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda *_: ""))
        ax.set_title(title, loc="left", pad=6)
        _month_ticks(ax, months, ui)
        _place_end_labels(ax, end_labels)
        if len(langs) >= 2 and ax is ax_views:
            ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.2),
                fontsize=6.5,
                frameon=False,
                ncol=min(6, len(langs)),
                handlelength=1.2,
                columnspacing=0.9,
                borderaxespad=0.1,
                labelcolor=TEXT_2,
            )


def _place_end_labels(ax, items: list[tuple[str, float, float]], min_gap_pt: float = 8.5) -> None:
    """Direct labels at line ends, nudged apart vertically so they never overlap."""
    if not items:
        return
    fig = ax.figure
    to_pt = 72.0 / fig.dpi
    pts = []
    for label, x, y in items:
        _, py = ax.transData.transform((x, y if y > 0 or ax.get_yscale() != "log" else 1e-9))
        pts.append([label, x, y, py * to_pt])
    pts.sort(key=lambda p: p[3])
    placed: list[float] = []
    for p in pts:
        target = p[3]
        if placed and target - placed[-1] < min_gap_pt:
            target = placed[-1] + min_gap_pt
        placed.append(target)
        p.append(target - p[3])
    for label, x, y, _py, dy in pts:
        ax.annotate(
            label,
            (x, y),
            xytext=(5, dy),
            textcoords="offset points",
            va="center",
            fontsize=7,
            color=TEXT,
            fontweight="bold",
            annotation_clip=False,
        )


def draw_growth(ax, analysis: dict, ui: str = "en") -> None:
    langs = _lang_order(analysis)
    rows = []
    for lang in langs:
        info = analysis["languages"][lang]
        sc = info["metrics"]["share_change"]
        rows.append((lang, 0.0 if sc is None else sc * 100, info["confidence"]))
    rows.sort(key=lambda r: r[1])
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ys = list(range(len(rows)))
    for y, (_lang, val, conf) in zip(ys, rows):
        ax.barh(
            y,
            val,
            height=0.55,
            color=SERIES[0],
            hatch="////" if conf == "LOW" else None,
            edgecolor=SURFACE if conf != "LOW" else "#ffffff",
            linewidth=0,
            alpha=0.55 if conf == "LOW" else 1.0,
            zorder=3,
        )
        label = f"{val:+.0f}% · {i18n.CONFIDENCE[ui][conf]}"
        ax.annotate(
            label,
            (val, y),
            xytext=(4 if val >= 0 else -4, 0),
            textcoords="offset points",
            ha="left" if val >= 0 else "right",
            va="center",
            fontsize=7,
            color=TEXT,
        )
    ax.axvline(0, color=TEXT_2, linewidth=0.8, zorder=4)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r[0]} · {languages.name(r[0], ui)}" for r in rows])
    lo = min([r[1] for r in rows] + [0])
    hi = max([r[1] for r in rows] + [0])
    span = max(hi - lo, 10)
    ax.set_xlim(lo - span * 0.45, hi + span * 0.45)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:+.0f}%"))
    comp = analysis.get("comparison_text_ui", {}).get(ui) or ""
    ax.set_title(i18n.label("chart_growth", ui, comparison=comp), loc="left")


def save_trend_png(analysis: dict, path: Path, ui: str = "en") -> Path | None:
    if not _lang_order(analysis):
        return None
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 5.2), sharex=False)
    fig.subplots_adjust(left=0.09, right=0.93, top=0.94, bottom=0.08, hspace=0.72)
    draw_trend(a1, a2, analysis, ui)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_growth_png(analysis: dict, path: Path, ui: str = "en") -> Path | None:
    langs = _lang_order(analysis)
    if len(langs) < 2:
        return None
    height = 1.1 + 0.42 * len(langs)
    fig, ax = plt.subplots(figsize=(7.2, height))
    fig.subplots_adjust(left=0.26, right=0.97, top=1 - 0.42 / height, bottom=0.42 / height)
    draw_growth(ax, analysis, ui)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def ensure_mpl_cache() -> None:
    """Keep matplotlib's font cache out of read-only homes (sandboxed agents)."""
    if "MPLCONFIGDIR" not in os.environ:
        try:
            from . import config

            d = config.cache_dir() / "mpl"
            d.mkdir(parents=True, exist_ok=True)
            os.environ["MPLCONFIGDIR"] = str(d)
        except OSError:
            pass
