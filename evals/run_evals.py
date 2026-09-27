#!/usr/bin/env python3
"""Run the eval cases through a real agent harness on a cheap model.

Each case runs in a fresh temporary project folder: the skill is copied into
`.claude/skills/` (read by both Claude Code and OpenCode), the agent gets the
prompt (and follow-ups in the same session), and everything it produced is
graded by evals/grade.py.

Examples:
  python3 evals/run_evals.py --harness claude --model haiku
  python3 evals/run_evals.py --harness opencode --model openrouter/qwen/qwen3.8-27b:free
  python3 evals/run_evals.py --harness claude --model haiku --cases if-pl-cs,astronomy-uk --baseline

Results: evals/workspace/<iteration>/... (raw, git-ignored) and
evals/results/<iteration>-<harness>.json (summary, committed).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
import grade  # noqa: E402

CLAUDE_TOOLS = [
    "Bash(uv run:*)", "Bash(python3:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(cp:*)", "Bash(mkdir:*)",
    "Read", "Write", "Edit", "Glob", "Grep", "Skill",
]
IGNORE = shutil.ignore_patterns("evals", "tests", "wiki-research", ".git", "__pycache__", ".venv", "*.pyc")


def install_skill(project: Path) -> None:
    dest = project / ".claude" / "skills" / SKILL.name
    shutil.copytree(SKILL, dest, ignore=IGNORE)


def run_claude(project: Path, prompt: str, model: str, session: str | None, timeout: int) -> dict:
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
           "--max-turns", "40", "--permission-mode", "acceptEdits", "--allowedTools", *CLAUDE_TOOLS]
    if session:
        cmd += ["--resume", session]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout)
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    tools = [c.get("name") for e in events if e.get("type") == "assistant"
             for c in (e.get("message", {}).get("content") or []) if c.get("type") == "tool_use"]
    return {
        "answer": result.get("result", ""),
        "session": result.get("session_id") or next((e.get("session_id") for e in events if e.get("session_id")), None),
        "duration_s": round(time.time() - t0, 1),
        "turns": result.get("num_turns"),
        "cost_usd": result.get("total_cost_usd"),
        "usage": result.get("usage"),
        "tool_calls": tools,
        "skill_loaded": any(e for e in events if e.get("type") == "assistant"
                            for c in (e.get("message", {}).get("content") or [])
                            if c.get("type") == "tool_use" and c.get("name") == "Skill"),
        "stderr": proc.stderr[-2000:],
        "raw": events,
    }


OPENCODE_RETRIES = (30, 60, 120)  # seconds to wait after a temporary provider error (free models: 429 upstream)
CONTINUE_PROMPT = "The previous step failed because of a temporary API error. Continue exactly where you stopped."


def _opencode_once(project: Path, prompt: str, model: str, session: str | None, timeout: int) -> dict:
    cmd = ["opencode", "run", "--auto", "--format", "json", "--model", model, "--dir", str(project)]
    if session:
        cmd += ["--session", session]
    cmd.append(prompt)
    proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout)
    events, texts, tools, sid, error, retryable = [], [], [], session, None, False
    for line in proc.stdout.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(e)
        sid = sid or e.get("sessionID") or (e.get("part") or {}).get("sessionID")
        part = e.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
        if part.get("type") == "tool":
            tools.append(part.get("tool"))
        if e.get("type") == "error":
            data = (e.get("error") or {}).get("data") or {}
            error = f"{data.get('statusCode', '')} {data.get('message', e.get('error'))}".strip()
            retryable = bool(data.get("isRetryable")) or data.get("statusCode") in (429, 502, 503)
    if error is None and proc.returncode != 0 and not texts:
        error = f"opencode exit {proc.returncode}: {proc.stderr.strip()[-300:]}"
    return {"texts": texts, "tools": tools, "events": events, "session": sid, "error": error,
            "retryable": retryable, "stderr": proc.stderr[-2000:]}


def run_opencode(project: Path, prompt: str, model: str, session: str | None, timeout: int) -> dict:
    """One user turn. Temporary provider errors (free-model rate limits) are retried by
    resuming the same session, so the agent keeps its progress; the retries are recorded."""
    (project / "opencode.json").write_text(json.dumps({"$schema": "https://opencode.ai/config.json",
                                                        "permission": {"edit": "allow", "bash": "allow"}}))
    t0 = time.time()
    texts, tools, events, retries, errors = [], [], [], 0, []
    r = _opencode_once(project, prompt, model, session, timeout)
    while True:
        texts += r["texts"]
        tools += r["tools"]
        events += r["events"]
        session = r["session"] or session
        if not r["error"]:
            break
        errors.append(r["error"])
        if not r["retryable"] or retries >= len(OPENCODE_RETRIES) or not session:
            break
        wait = OPENCODE_RETRIES[retries]
        retries += 1
        print(f"      provider error ({r['error'][:80]}), retry {retries} in {wait}s", flush=True)
        time.sleep(wait)
        r = _opencode_once(project, CONTINUE_PROMPT, model, session, timeout)
    final_error = r["error"]
    return {
        "answer": texts[-1] if texts else "",
        "session": session,
        "duration_s": round(time.time() - t0, 1),
        "turns": None,
        "cost_usd": None,
        "tool_calls": tools,
        "skill_loaded": "skill" in tools,
        "retries": retries,
        "provider_errors": errors,
        "error": final_error,
        "stderr": r["stderr"],
        "raw": events,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness", choices=["claude", "opencode"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--cases", help="comma-separated case ids (default: all)")
    ap.add_argument("--baseline", action="store_true", help="also run each case WITHOUT the skill")
    ap.add_argument("--iteration", default=datetime.now(timezone.utc).strftime("iter-%Y%m%d-%H%M"))
    ap.add_argument("--timeout", type=int, default=900, help="seconds per agent turn")
    args = ap.parse_args()

    if not shutil.which(args.harness):
        print(f"'{args.harness}' CLI not found in PATH", file=sys.stderr)
        return 2
    cases = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))["evals"]
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    runner = run_claude if args.harness == "claude" else run_opencode
    work = HERE / "workspace" / args.iteration
    work.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("WIKI_RESEARCH_CACHE", str(HERE / "workspace" / "cache"))

    results = []
    configs = ["with_skill"] + (["without_skill"] if args.baseline else [])
    for case in cases:
        for config in configs:
            project = Path(tempfile.mkdtemp(prefix=f"eval-{case['id']}-"))
            if config == "with_skill":
                install_skill(project)
            print(f"[{case['id']} / {config}] running...", flush=True)
            turns, session = [], None
            for prompt in [case["prompt"], *case.get("followups", [])]:
                try:
                    r = runner(project, prompt, args.model, session, args.timeout)
                except subprocess.TimeoutExpired:
                    r = {"answer": "", "error": "timeout", "tool_calls": [], "raw": [], "duration_s": args.timeout}
                session = r.get("session") or session
                turns.append(r)
            out = work / case["id"] / config
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            if (project / "wiki-research").exists():
                shutil.copytree(project / "wiki-research", out / "wiki-research")
            for pdf in project.glob("*.pdf"):
                shutil.copy(pdf, out / pdf.name)
            (out / "transcript.json").write_text(json.dumps([t.pop("raw", []) for t in turns], ensure_ascii=False))
            (out / "answers.json").write_text(json.dumps(
                [{"answer": t.get("answer", ""), "error": t.get("error")} for t in turns], ensure_ascii=False, indent=1))
            (out / "answer.md").write_text("\n\n---\n\n".join(t.get("answer", "") for t in turns), encoding="utf-8")
            own_code = [str(p.relative_to(project)) for p in project.rglob("*.py") if ".claude" not in p.parts]
            timing = {
                "duration_s": round(sum(t.get("duration_s") or 0 for t in turns), 1),
                "cost_usd": round(sum(t.get("cost_usd") or 0 for t in turns), 4),
                "tool_calls": sum(len(t.get("tool_calls") or []) for t in turns),
                "turns": [t.get("turns") for t in turns],
                "provider_retries": sum(t.get("retries") or 0 for t in turns),
            }
            (out / "timing.json").write_text(json.dumps(timing, indent=1))
            g = grade.grade_case(case, out, turns, own_code, config)
            (out / "grading.json").write_text(json.dumps(g, ensure_ascii=False, indent=1))
            results.append({"case": case["id"], "config": config, **timing, **g["summary"]})
            print(f"   -> {g['summary']['passed']}/{g['summary']['total']} checks, {timing['duration_s']}s, "
                  f"{timing['tool_calls']} tool calls, ${timing['cost_usd']}", flush=True)
            for a in g["checks"]:
                if not a["passed"]:
                    print(f"      FAIL {a['name']}: {a['evidence'][:160]}")
            shutil.rmtree(project, ignore_errors=True)

    bench = grade.benchmark(results)
    summary = {"iteration": args.iteration, "harness": args.harness, "model": args.model,
               "date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": results, "benchmark": bench}
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"{args.iteration}-{args.harness}-{args.model.replace('/', '_').replace(':', '_')}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print("\n" + grade.table(results))
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
