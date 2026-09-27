"""Code-based grading of eval outputs (no LLM judge needed for these checks).

Checks per case:
- used_cli        the agent ran `wiki.py research` successfully (skill's own command log)
- no_own_code     the agent did not write its own Python to fetch/analyse data
- numbers_match   every number in the final answer exists in the run(s) (wikitrends.textcheck)
- confidence      the answer states a confidence level
- limitation      the answer mentions at least one limitation
- language        the answer is in the prompt's language
- pdf_one_page    (if required) a one-page PDF was produced
- case checks     regex / concept-count / rerun checks from evals.json
Negative cases (the skill must NOT be used) pass when no research command ran.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from wikitrends.textcheck import NOISE_RE, check_text  # noqa: E402

_CONF_WORD = r"(?:confidence|довір\w*|надійн\w*|впевнен\w*)"
_CONF_LEVEL = r"(?:high|medium|low|висок\w*|середн\w*|низьк\w*)"
# a confidence word next to a level ("довіра висока", "HIGH confidence"), or the tool's own HIGH/MEDIUM/LOW;
# upper case = the level copied from the tool into a table; "довіряти" alone is not a stated level
CONF_RE = re.compile(
    rf"{_CONF_WORD}[^.\n]{{0,40}}\b{_CONF_LEVEL}\b|\b{_CONF_LEVEL}\b[^.\n]{{0,40}}{_CONF_WORD}|\b(?-i:HIGH|MEDIUM|LOW|ВИСОК\w*|СЕРЕДН\w*|НИЗЬК\w*)\b",
    re.I,
)
LIMIT_RE = re.compile(
    r"(не означа|не є |обмеж|≠|готовн\w* платити|цікавість|not (the same|equal)|limitation|willingness|curiosity|"
    r"doesn't mean|does not mean|country|\bкраїн|caveat|застереж)",  # \b: not "україномовна"
    re.I,
)


def _cyr_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-zЀ-ӿ]", NOISE_RE.sub(" ", text))  # ignore paths, code, urls
    return sum(1 for ch in letters if "Ѐ" <= ch <= "ӿ") / len(letters) if letters else 0.0


def _load_runs(out: Path) -> list[dict]:
    runs = []
    for p in sorted((out / "wiki-research" / "runs").glob("*/summary.json")):
        runs.append(json.loads(p.read_text(encoding="utf-8")))
    return runs


def _log(out: Path) -> list[dict]:
    p = out / "wiki-research" / ".log" / "commands.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _merged_summary(runs: list[dict]) -> dict:
    """Union of facts across runs (follow-ups legitimately quote earlier runs)."""
    langs, ranking = {}, []
    for i, r in enumerate(runs):
        for lang, info in r["analysis"]["languages"].items():
            langs[f"{lang}#{i}"] = info
        ranking += r["analysis"].get("ranking", [])
    return {"analysis": {"languages": langs, "ranking": ranking, "window": runs[-1]["analysis"]["window"] if runs else {}}}


def grade_case(case: dict, out: Path, turns: list[dict], own_code: list[str], config: str) -> dict:
    answer_all = "\n".join(t.get("answer", "") for t in turns)
    final = turns[-1].get("answer", "") if turns else ""
    log = _log(out)
    research_ok = [e for e in log if e["argv"] and e["argv"][0] == "research" and e["status"] == 0]
    runs = _load_runs(out)
    checks = []

    def add(name: str, passed: bool, evidence: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    errors = [t["error"] for t in turns if t.get("error")]
    add("finished", not errors, "; ".join(errors)[:300] or "every turn completed")
    if case.get("negative"):
        add("skill_not_used", not log, f"{len(log)} skill commands logged")
        add("answered", len(final.strip()) > 50, f"answer length {len(final)}")
    else:
        add("used_cli", bool(research_ok), f"{len(research_ok)} successful research runs")
        add("no_own_code", not own_code, ", ".join(own_code) or "no .py files written by the agent")
        if runs:
            res = check_text(answer_all, _merged_summary(runs))
            add("numbers_match", not res.errors, f"{res.checked} numbers checked; " + "; ".join(res.errors[:3]))
        else:
            add("numbers_match", False, "no run to compare with")
        conf = CONF_RE.search(answer_all)  # any turn: a follow-up that only delivers the PDF need not repeat it
        add("confidence", bool(conf), conf.group(0) if conf else "no confidence wording")
        add("limitation", bool(LIMIT_RE.search(answer_all)), "found" if LIMIT_RE.search(answer_all) else "no limitation wording")
        wants_uk = _cyr_ratio(case["prompt"]) > 0.5
        ratio = _cyr_ratio(final)
        add("language", (ratio > 0.5) == wants_uk, f"cyrillic ratio {ratio:.2f}, expected {'uk' if wants_uk else 'en'}")
        if case.get("requires_pdf"):
            pdfs = list(out.rglob("*.pdf"))
            pages = [_pdf_pages(p) for p in pdfs]
            add("pdf_one_page", any(n == 1 for n in pages), f"{len(pdfs)} pdf(s), pages {pages}")

    for c in case.get("checks", []):
        kind = c["type"]
        if kind == "regex":
            m = re.search(c["pattern"], answer_all, re.I)
            add(c["description"], bool(m), m.group(0) if m else f"pattern {c['pattern']} not found")
        elif kind == "min_concepts":
            n = max((len(r["concepts"]) for r in runs), default=0)
            add(c["description"], n >= c["value"], f"max concepts in a run: {n}")
        elif kind == "min_research_runs":
            add(c["description"], len(research_ok) >= c["value"], f"{len(research_ok)} research runs")
        elif kind == "log_contains":
            hit = any(re.search(c["pattern"], " ".join(e["argv"])) for e in research_ok)
            add(c["description"], hit, "found in command log" if hit else "not in command log")

    passed = sum(1 for c in checks if c["passed"])
    return {"config": config, "checks": checks, "summary": {"passed": passed, "total": len(checks),
                                                            "pass_rate": round(passed / len(checks), 3) if checks else 1.0}}


def _pdf_pages(path: Path) -> int:
    data = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def benchmark(results: list[dict]) -> dict:
    out = {}
    for config in sorted({r["config"] for r in results}):
        rows = [r for r in results if r["config"] == config]

        def stat(key, rows=rows):
            vals = [r[key] for r in rows if r.get(key) is not None]
            if not vals:
                return None
            return {"mean": round(statistics.mean(vals), 3), "stddev": round(statistics.pstdev(vals), 3)}

        out[config] = {"cases": len(rows), "pass_rate": stat("pass_rate"), "duration_s": stat("duration_s"),
                       "tool_calls": stat("tool_calls"), "cost_usd": stat("cost_usd")}
    return out


def table(results: list[dict]) -> str:
    lines = [f"{'case':<24}{'config':<15}{'checks':>8}{'time s':>9}{'tools':>7}{'cost $':>9}"]
    for r in results:
        lines.append(f"{r['case']:<24}{r['config']:<15}{r['passed']:>4}/{r['total']:<3}{r['duration_s']:>9}"
                     f"{r['tool_calls']:>7}{r['cost_usd']:>9}")
    return "\n".join(lines)


if __name__ == "__main__":  # regrade a finished workspace: python3 evals/grade.py <workspace/iteration>
    root = Path(sys.argv[1])
    cases = {c["id"]: c for c in json.loads((Path(__file__).parent / "evals.json").read_text())["evals"]}
    for d in sorted(root.glob("*/*")):
        if (d / "answers.json").exists():  # exact per-turn answers (newer runs)
            turns = json.loads((d / "answers.json").read_text(encoding="utf-8"))
        else:  # older runs: answer.md joined with a separator the agent may also use
            answer = (d / "answer.md").read_text(encoding="utf-8") if (d / "answer.md").exists() else ""
            turns = [{"answer": a} for a in answer.split("\n\n---\n\n")]
        g = grade_case(cases[d.parent.name], d, turns, [], d.name)
        print(d.parent.name, d.name, g["summary"])
