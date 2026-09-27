"""One-page A4 PDF report rendered with matplotlib only (no extra dependencies).

Who writes what:
- code: numbers table, charts, confidence reasons, limitations, method, footer
  (always consistent with summary.json)
- agent: headline, answer, recommendation, next steps (short, checked by
  textcheck before rendering)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.textpath import TextToPath  # noqa: E402

from . import charts, i18n, languages  # noqa: E402
from .analyze import fmt_int, fmt_pct  # noqa: E402
from .textcheck import check_text  # noqa: E402

PAGE_W, PAGE_H = 8.27, 11.69
MX, MTOP, MBOTTOM = 0.55, 0.5, 0.42
CONTENT_W = PAGE_W - 2 * MX

LIMITS = {"headline": 120, "answer": 560, "recommendation": 380, "next_step": 140, "next_steps": 3}


class ReportError(Exception):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.warnings = warnings or []


def validate_narrative(narr: dict, summary: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("headline", "answer", "recommendation"):
        val = narr.get(key)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"narrative.{key} is missing or empty.")
        elif len(val) > LIMITS[key]:
            errors.append(f"narrative.{key} is {len(val)} characters; the limit is {LIMITS[key]}. Shorten it.")
    steps = narr.get("next_steps", [])
    if not isinstance(steps, list):
        errors.append("narrative.next_steps must be a list of short strings.")
        steps = []
    if len(steps) > LIMITS["next_steps"]:
        errors.append(f"narrative.next_steps has {len(steps)} items; the limit is {LIMITS['next_steps']}.")
    for i, s in enumerate(steps):
        if not isinstance(s, str) or len(s) > LIMITS["next_step"]:
            errors.append(f"narrative.next_steps[{i}] must be a string of at most {LIMITS['next_step']} characters.")
    if errors:
        return errors, warnings
    text = "\n".join([narr["headline"], narr["answer"], narr["recommendation"], *steps])
    res = check_text(text, summary)
    errors += res.errors
    warnings += res.warnings
    return errors, warnings


class _Page:
    def __init__(self) -> None:
        self.fig = plt.figure(figsize=(PAGE_W, PAGE_H))
        self.y = MTOP
        self.ttp = TextToPath()

    def width_in(self, text: str, size: float, weight: str = "normal") -> float:
        prop = FontProperties(family="DejaVu Sans", size=size, weight=weight)
        w, _h, _d = self.ttp.get_text_width_height_descent(text or " ", prop, ismath=False)
        return w / 72.0

    def wrap(self, text: str, size: float, max_w: float, weight: str = "normal") -> list[str]:
        lines: list[str] = []
        for para in str(text).split("\n"):
            words = para.split()
            if not words:
                lines.append("")
                continue
            cur = words[0]
            for w in words[1:]:
                trial = cur + " " + w
                if self.width_in(trial, size, weight) <= max_w:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
        return lines

    def fy(self, y_in: float) -> float:
        return 1 - y_in / PAGE_H

    def fx(self, x_in: float) -> float:
        return x_in / PAGE_W

    def lines(self, lines: list[str], x: float, size: float, color: str = charts.TEXT, weight: str = "normal",
              lh: float = 1.32, advance: bool = True, y: float | None = None) -> float:
        y0 = self.y if y is None else y
        step = size * lh / 72.0
        for i, ln in enumerate(lines):
            self.fig.text(self.fx(x), self.fy(y0 + step * (i + 0.8)), ln, fontsize=size, color=color,
                          weight=weight, va="baseline", ha="left")
        h = step * len(lines)
        if advance:
            self.y = y0 + h
        return h

    def para(self, text: str, size: float, x: float = MX, width: float = CONTENT_W, **kw) -> float:
        return self.lines(self.wrap(text, size, width, kw.get("weight", "normal")), x, size, **kw)

    def heading(self, text: str, x: float = MX, y: float | None = None, advance: bool = True) -> float:
        return self.lines([text.upper()], x, 7.2, color=charts.TEXT_2, weight="bold", advance=advance, y=y)

    def rule(self, y: float | None = None) -> None:
        yy = self.fy(self.y if y is None else y)
        self.fig.add_artist(Line2D([self.fx(MX), self.fx(MX + CONTENT_W)], [yy, yy], color=charts.GRID, linewidth=0.7))

    def gap(self, inches: float) -> None:
        self.y += inches


def _topic_label(summary: dict, ui: str) -> str:
    names = []
    for c in summary["concepts"]:
        lab = (c.get("labels") or {}).get(ui) or c["label"]
        names.append(lab)
    text = ", ".join(names)
    return text if len(text) <= 70 else text[:67] + "…"


def _why_lines(summary: dict, ui: str, max_per_lang: int = 3) -> list[str]:
    out = []
    order = {"critical": 0, "warn": 1, "info": 2}
    for lang, info in summary["analysis"]["languages"].items():
        flags = sorted(info.get("flags", []), key=lambda f: order.get(f["severity"], 3))
        conf = i18n.CONFIDENCE[ui].get(info.get("confidence", "NONE"), "")
        head = f"{lang} ({conf})" if info.get("status") == "ok" else f"{lang}"
        texts = [i18n.flag_text(f["id"], f["params"], ui) for f in flags if f["severity"] in ("critical", "warn")]
        if not texts:
            texts = [i18n.flag_text(f["id"], f["params"], ui) for f in flags[:1]]
        if not texts and info.get("status") == "ok":
            texts = ["no warning signs" if ui == "en" else "без тривожних сигналів"]
        out.append(f"{head}: " + "; ".join(texts[:max_per_lang]))
    return out


def build_pdf(summary: dict, narrative: dict, out_path: Path, ui: str = "en") -> Path:
    """Render the report, tightening the layout step by step if it does not fit one page."""
    last: ReportError | None = None
    for compact in (0, 1, 2):
        try:
            return _build_pdf(summary, narrative, out_path, ui, compact)
        except ReportError as e:
            last = e
    assert last is not None
    raise last


def _build_pdf(summary: dict, narrative: dict, out_path: Path, ui: str, compact: int) -> Path:
    ui = ui if ui in i18n.UI_LANGS else "en"
    an = summary["analysis"]
    an.setdefault("window", {})["months_list"] = summary["window"]["months_list"]
    an["comparison_text_ui"] = summary.get("comparison_text_ui", {})
    langs_all = list(an["languages"])
    langs_ok = [l for l in langs_all if an["languages"][l].get("status") == "ok"]
    page = _Page()
    fig = page.fig

    # ---- title
    page.para(i18n.label("report_title", ui, topic=_topic_label(summary, ui)), 15, weight="bold")
    lang_names = ", ".join(f"{l} ({languages.name(l, ui)})" for l in langs_all)
    page.gap(0.02)
    page.para(
        i18n.label("subtitle", ui, langs=lang_names, window=f"{summary['window']['start']}…{summary['window']['end']}"),
        8,
        color=charts.TEXT_2,
    )
    page.gap(0.14)

    # ---- answer box (agent text)
    box_top = page.y
    inner_x, inner_w = MX + 0.14, CONTENT_W - 0.28
    head_lines = page.wrap(narrative["headline"], 10.5, inner_w, "bold")
    ans_lines = page.wrap(narrative["answer"], 8.6, inner_w)
    box_h = 0.12 + len(head_lines) * 10.5 * 1.3 / 72 + 0.05 + len(ans_lines) * 8.6 * 1.35 / 72 + 0.12
    fig.add_artist(
        FancyBboxPatch(
            (page.fx(MX), page.fy(box_top + box_h)),
            CONTENT_W / PAGE_W,
            box_h / PAGE_H,
            boxstyle="round,pad=0,rounding_size=0.006",
            transform=fig.transFigure,
            facecolor="#f4f7fc",
            edgecolor="none",
        )
    )
    page.gap(0.12)
    page.lines(head_lines, inner_x, 10.5, weight="bold", lh=1.3)
    page.gap(0.05)
    page.lines(ans_lines, inner_x, 8.6, lh=1.35)
    page.y = box_top + box_h + 0.16

    # ---- numbers table
    page.heading(i18n.label("key_numbers", ui))
    page.gap(0.03)
    cols = [
        (i18n.label("language", ui), 1.85, "left"),
        (i18n.label("avg_views", ui), 1.1, "right"),
        (i18n.label("change_views", ui), 1.1, "right"),
        (i18n.label("change_share", ui), 1.1, "right"),
        (i18n.label("direction", ui), 1.05, "right"),
        (i18n.label("confidence", ui), 0.95, "right"),
    ]
    row_h = 0.2

    def row(values: list[str], bold: bool = False, color: str = charts.TEXT) -> None:
        x = MX
        for (_, w, align), v in zip(cols, values):
            tx = x if align == "left" else x + w - 0.04
            fig.text(page.fx(tx), page.fy(page.y + row_h * 0.68), v, fontsize=7.6, ha=align, va="baseline",
                     weight="bold" if bold else "normal", color=color)
            x += w
        page.y += row_h

    row([c[0] for c in cols], bold=True, color=charts.TEXT_2)
    page.rule()
    for lang in langs_all[:10]:
        info = an["languages"][lang]
        name = f"{lang} · {languages.name(lang, ui)}"
        if info.get("status") != "ok":
            row([name, "—", "—", "—", i18n.label("no_data", ui), "—"], color=charts.TEXT_2)
        else:
            m = info["metrics"]
            row(
                [
                    name,
                    fmt_int(m["avg_monthly_views_recent"]),
                    fmt_pct(m["views_change"]),
                    fmt_pct(m["share_change"]),
                    i18n.DIRECTION[ui][info["direction"]],
                    i18n.CONFIDENCE[ui][info["confidence"]],
                ]
            )
        page.rule()
    page.gap(0.05)
    comp = summary.get("comparison_text_ui", {}).get(ui, "")
    page.para("* " + i18n.label("method_text", ui, comparison=comp), 6.4, color=charts.TEXT_2)
    page.gap(0.06)

    # ---- charts (axes boxes exclude titles above and tick labels below)
    title_space, tick_space = 0.3, 0.36
    if langs_ok:
        page.gap(0.08)
        plot_h = (1.95, 1.6, 1.3)[compact]
        y_axis_w = 0.42
        panel_w = (CONTENT_W - 0.5) / 2
        bottom = page.y + title_space + plot_h
        ax1 = fig.add_axes((page.fx(MX + y_axis_w), page.fy(bottom), (panel_w - y_axis_w - 0.25) / PAGE_W, plot_h / PAGE_H))
        ax2 = fig.add_axes(
            (page.fx(MX + panel_w + 0.5 + y_axis_w), page.fy(bottom), (panel_w - y_axis_w - 0.25) / PAGE_W, plot_h / PAGE_H)
        )
        charts.draw_trend(ax1, ax2, an, ui)
        page.y = bottom + tick_space + (0.2 if len(langs_ok) >= 2 else 0)
        if len(langs_ok) >= 2:
            page.gap(0.06)
            gh = (0.22, 0.18, 0.15)[compact] * len(langs_ok) + 0.1
            gbottom = page.y + title_space + gh
            ax3 = fig.add_axes((page.fx(MX + 1.6), page.fy(gbottom), (CONTENT_W - 1.8) / PAGE_W, gh / PAGE_H))
            charts.draw_growth(ax3, an, ui)
            page.y = gbottom + 0.28
    page.gap(0.12)

    # ---- two columns: why (code) | recommendation + next steps (agent)
    col_w = (CONTENT_W - 0.3) / 2
    top = page.y
    page.heading(i18n.label("why", ui), x=MX)
    why = []
    for ln in _why_lines(summary, ui, max_per_lang=(3, 2, 1)[compact]):
        why += page.wrap("• " + ln, 7.3, col_w)
    page.lines(why[: (14, 12, 10)[compact]], MX, 7.3, lh=1.3)
    left_bottom = page.y
    page.y = top
    rx = MX + col_w + 0.3
    page.heading(i18n.label("recommendation", ui), x=rx)
    page.lines(page.wrap(narrative["recommendation"], 7.8, col_w), rx, 7.8, lh=1.32)
    if narrative.get("next_steps"):
        page.gap(0.06)
        page.heading(i18n.label("next_steps", ui), x=rx)
        steps = []
        for s in narrative["next_steps"]:
            steps += page.wrap("→ " + s, 7.6, col_w)
        page.lines(steps, rx, 7.6, lh=1.3)
    page.y = max(page.y, left_bottom) + 0.12

    # ---- limitations (code)
    page.heading(i18n.label("limitations", ui))
    lim = list(i18n.LIMITATIONS[ui])
    for issue in an.get("known_issues", []):
        lim.append(issue.get(ui) or issue.get("en"))
    for g in an.get("global_flags", []):
        lim.append(i18n.flag_text(g["id"], g.get("params", {}), ui))
    lim_lines = []
    for item in lim:
        lim_lines += page.wrap("• " + item, 6.9, CONTENT_W)
    page.lines(lim_lines, MX, 6.9, color=charts.TEXT_2, lh=1.28)
    page.gap(0.08)

    # ---- articles + footer
    arts = []
    for c in summary["concepts"]:
        titles = "; ".join(f"{l}: {t}" for l, t in c["titles"].items() if t)
        arts.append(f"{c['label']} [{c['qid']}] — {titles or ('no articles' if ui == 'en' else 'статей немає')}")
    art_lines = page.wrap(i18n.label("articles", ui) + ": " + " | ".join(arts), 6.3, CONTENT_W)
    footer = i18n.label(
        "generated",
        ui,
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        run_id=summary["run_id"],
    )
    footer_lines = page.wrap(footer, 6.3, CONTENT_W)
    needed = (len(art_lines) + len(footer_lines)) * 6.3 * 1.3 / 72
    if page.y + needed > PAGE_H - MBOTTOM:
        plt.close(fig)
        raise ReportError(
            [
                "The report does not fit on one page. Shorten narrative.answer and narrative.recommendation "
                "(aim for 2 short sentences each) or analyse fewer languages/topics."
            ]
        )
    page.y = PAGE_H - MBOTTOM - needed
    page.lines(art_lines, MX, 6.3, color=charts.MUTED, lh=1.3)
    page.lines(footer_lines, MX, 6.3, color=charts.MUTED, lh=1.3)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format="pdf")
    plt.close(fig)
    return out_path


def load_narrative(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ReportError([f"Narrative file not found: {path}"]) from e
    except json.JSONDecodeError as e:
        raise ReportError([f"Narrative file is not valid JSON ({e}). Use the template in assets/narrative.template.json."]) from e
