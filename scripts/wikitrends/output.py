"""Compact, English, plain-text summary printed after `research` (read by the agent).

Kept short on purpose (~20-45 lines): every number the agent may quote is
here, every judgement comes with its reason, and the last block says what to
do next. Details stay in the run folder.
"""

from __future__ import annotations

from . import i18n, languages
from .analyze import fmt_int, fmt_pct


def _concept_line(c: dict, langs: list[str]) -> str:
    titles = ", ".join(f"{l}: {c['titles'].get(l)}" if c["titles"].get(l) else f"{l}: —" for l in langs)
    return f"  {c['label']} [{c['qid']}] {titles}"


def render_research(summary: dict, skill_dir: str = "<SKILL_DIR>") -> str:
    an = summary["analysis"]
    langs = list(an["languages"])
    L: list[str] = []
    L.append(f"RUN {summary['run_id']}")
    L.append(f"SAVED {summary['run_path']}")
    L.append(
        f"WINDOW {summary['window']['start']}..{summary['window']['end']} ({summary['window']['months']} full months) "
        "· human views (agent=user) · all devices"
    )
    L.append(f"CHANGE = {summary['comparison_text_ui']['en']}; SHARE = views per million views of that Wikipedia edition")
    L.append("CONCEPTS (Wikidata id, article per language)")
    for c in summary["concepts"]:
        L.append(_concept_line(c, langs))
    if an.get("basket_mode") == "common" and any(i.get("excluded_from_comparison") for i in an["languages"].values()):
        L.append("  (only concepts present in every analysed language are used for the comparison)")

    L.append("")
    hdr = f"{'LANG':<6}{'VIEWS/MO':>10}{'VIEWS CHG':>11}{'SHARE CHG':>11}{'UP MONTHS':>11}{'TREND p':>9}  {'DIRECTION':<10} CONFIDENCE"
    L.append(hdr)
    for lang in langs:
        info = an["languages"][lang]
        if info.get("status") != "ok":
            reason = next((f for f in info.get("flags", []) if f["severity"] == "critical"), None)
            L.append(f"{lang:<6}NO DATA — {reason['message'] if reason else 'no article'}")
            continue
        m = info["metrics"]
        cons = m.get("consistency")
        cons_s = f"{cons['months_up']}/{cons['of']}" if cons else "n/a"
        L.append(
            f"{lang:<6}{fmt_int(m['avg_monthly_views_recent']):>10}{fmt_pct(m['views_change'], 1):>11}"
            f"{fmt_pct(m['share_change'], 1):>11}{cons_s:>11}{m['trend']['p']:>9.3f}  {info['direction']:<10} {info['confidence']}"
        )

    multi = [l for l in langs if an["languages"][l].get("status") == "ok" and len(an["languages"][l].get("per_concept", {})) > 1]
    if multi:
        L.append("")
        L.append("BY CONCEPT (share change, views/month)")
        for lang in multi:
            parts = []
            for c in an["languages"][lang]["per_concept"].values():
                parts.append(f"{c['label']} {fmt_pct(c['share_change'])} ({fmt_int(c['avg_monthly_views_recent'])})")
            L.append(f"  {lang}: " + "; ".join(parts))

    L.append("")
    L.append("WHY (reasons behind each confidence level)")
    any_reason = False
    for lang in langs:
        info = an["languages"][lang]
        for f in info.get("flags", []):
            if f["id"] in ("no_article", "no_views"):
                continue
            L.append(f"  {lang} [{f['severity']}] {f['message']}")
            any_reason = True
    if not any_reason:
        L.append("  no warning signs")

    ranking = an.get("ranking", [])
    if len(ranking) >= 2:
        w = an["weights"]
        L.append("")
        L.append(
            f"RANKING (score = {w['volume']:g}*volume + {w['growth']:g}*growth + {w['reliability']:g}*reliability, "
            "each scaled 0-1 across these languages)"
        )
        for r in ranking:
            L.append(f"  {r['rank']}. {r['lang']} ({languages.name(r['lang'])}) score {r['score']:.2f} — {r['why']}")

    checks = []
    for c in summary["concepts"]:
        alts = ", ".join(f"{a['qid']} ({a['description'][:40]}, {a['sitelinks']} wikis)" for a in c.get("alternatives", [])[:2])
        if c.get("ambiguous"):
            checks.append(
                f"'{c['query']}' is ambiguous: using {c['qid']} ({c['description'][:60]}, {c['sitelinks']} wikis). "
                f"Alternatives: {alts}. Tell the user which meaning you analysed; if wrong, rerun with --qids <id>."
            )
        elif c.get("weak_match"):
            checks.append(f"No exact match for '{c['query']}': using closest {c['qid']} ({c['label']}). Alternatives: {alts}.")
    missing_langs = [l for l in langs if an["languages"][l].get("status") != "ok"]
    if missing_langs:
        checks.append(
            f"No article in: {', '.join(missing_langs)}. Say so explicitly; do not estimate numbers for them."
        )
    for qid, props in (summary.get("proxies") or {}).items():
        label = next((c["label"] for c in summary["concepts"] if c["qid"] == qid), qid)
        if props:
            opts = "; ".join(
                f"{p['label']} [{p['qid']}] ({p['relation']}: " + ", ".join(f"{l}: {t}" for l, t in p["titles"].items()) + ")"
                for p in props[:3]
            )
            checks.append(
                f"Broader concepts of '{label}' that exist in every language (possible proxies): {opts}. "
                f"A proxy measures a broader topic: tell the user, then rerun with --qids <id> if they accept."
            )
        else:
            checks.append(f"No broader concept of '{label}' exists in every language; compare only where articles exist.")
    if checks:  # placed at the top so a quick reader cannot miss it
        L[2:2] = ["", "CHECK BEFORE ANSWERING (mention each point in your answer)"] + [f"  - {c}" for c in checks] + [""]

    notes = list(summary.get("notes", []))
    notes += [i.get("en", "") for i in an.get("known_issues", [])]
    notes += [g["message"] for g in an.get("global_flags", [])]
    if summary.get("redirects_used"):
        notes.append(
            "Views of redirect titles were added for: " + ", ".join(summary["redirects_used"].keys()) + " (renamed articles)."
        )
    if notes:
        L.append("")
        L.append("NOTES")
        L += [f"  - {n}" for n in notes if n]

    files = ", ".join(v for v in summary.get("files", {}).values())
    L.append("")
    L.append(f"FILES (in SAVED folder): {files}")
    L.append("NEXT")
    L.append("  - Answer from these numbers only; give the direction, the confidence and its main reason, and 1-2 limitations.")
    L.append(
        f"  - One-page PDF: copy {skill_dir}/assets/narrative.template.json, fill it, then run: "
        f"wiki.py report --run {summary['run_id']} --narrative <file> --ui <uk|en>"
    )
    L.append(f"  - Verify a text answer's numbers: wiki.py check --run {summary['run_id']} --text <file>")
    return "\n".join(L)


def render_resolve(concepts: list, langs: list[str], notes: list[str]) -> str:
    L = ["CONCEPTS (Wikidata id, sitelinks = number of wikis with an article)"]
    for c in concepts:
        d = c.to_dict() if hasattr(c, "to_dict") else c
        flag = " AMBIGUOUS" if d.get("ambiguous") else (" WEAK MATCH" if d.get("weak_match") else "")
        L.append(f"- '{d['query']}' -> {d['qid']} {d['label']} ({d['sitelinks']} wikis){flag}: {d['description'][:80]}")
        for l in langs:
            t = d["titles"].get(l)
            L.append(f"    {l}: {t if t else '— no article'}")
        for a in d.get("alternatives", [])[:3]:
            L.append(f"    alt: {a['qid']} {a['label']} ({a['sitelinks']} wikis): {a['description'][:60]}")
    if notes:
        L.append("NOTES")
        L += [f"- {n}" for n in notes]
    return "\n".join(L)


def render_runs(rows: list[dict]) -> str:
    if not rows:
        return "No runs yet."
    L = ["RECENT RUNS (newest first)"]
    for r in rows:
        verdicts = ", ".join(f"{k}: {v}" for k, v in r.get("verdicts", {}).items())
        L.append(f"- {r['run_id']} | {', '.join(r['topics'])} | {r['window']} | {verdicts}")
    return "\n".join(L)


def lang_label(code: str, ui: str) -> str:
    return f"{code} ({languages.name(code, ui)})"


__all__ = ["render_research", "render_resolve", "render_runs", "i18n"]
