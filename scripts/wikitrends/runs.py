"""Run folders, the run index, and comparison of two runs (for follow-up questions)."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .analyze import fmt_int, fmt_pct

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh", "з": "z",
    "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ь": "", "ю": "iu", "я": "ia", "ы": "y", "э": "e", "ё": "e", "ъ": "",
}


def slug(text: str, max_len: int = 28) -> str:
    t = "".join(_CYR.get(ch, ch) for ch in text.lower())
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t[:max_len].rstrip("-")) or "topic"


def new_run_id(topics: list[str], langs: list[str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slug(topics[0] if topics else 'topic', 24)}-{'-'.join(langs[:4])}"


def runs_root(out_dir: Path) -> Path:
    return Path(out_dir) / "runs"


def index_path(out_dir: Path) -> Path:
    return Path(out_dir) / "runs.jsonl"


def append_index(out_dir: Path, entry: dict) -> None:
    p = index_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_runs(out_dir: Path, limit: int = 10) -> list[dict]:
    p = index_path(out_dir)
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[-limit:][::-1]


class RunNotFound(Exception):
    pass


def resolve_run(out_dir: Path, ref: str) -> Path:
    ref = (ref or "latest").strip()
    path = Path(ref)
    if path.is_dir() and (path / "summary.json").exists():
        return path
    root = runs_root(out_dir)
    if ref == "latest":
        rows = list_runs(out_dir, 1)
        if not rows:
            raise RunNotFound(f"No runs yet in {out_dir}. Run `wiki.py research ...` first.")
        ref = rows[0]["run_id"]
    if (root / ref / "summary.json").exists():
        return root / ref
    matches = sorted(p for p in root.glob(f"{ref}*") if (p / "summary.json").exists()) if root.exists() else []
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RunNotFound(f"Run '{ref}' not found in {root}. See `wiki.py runs`.")
    raise RunNotFound(f"Run '{ref}' is ambiguous: {', '.join(m.name for m in matches[:5])}")


def load_summary(run_path: Path) -> dict:
    return json.loads((Path(run_path) / "summary.json").read_text(encoding="utf-8"))


def index_entry(summary: dict) -> dict:
    langs = summary["analysis"]["languages"]
    return {
        "run_id": summary["run_id"],
        "created_at": summary["created_at"],
        "topics": [c["label"] for c in summary["concepts"]],
        "qids": [c["qid"] for c in summary["concepts"]],
        "langs": list(langs),
        "window": f"{summary['window']['start']}..{summary['window']['end']}",
        "verdicts": {l: f"{i.get('direction')}/{i.get('confidence')}" for l, i in langs.items()},
        "path": summary.get("run_path"),
    }


def diff_runs(a: dict, b: dict) -> list[str]:
    """Human-readable differences between run A (before) and run B (after)."""
    out: list[str] = [f"A = {a['run_id']}", f"B = {b['run_id']}"]
    pa, pb = a["params"], b["params"]
    for key in ("topics", "qids", "langs", "window", "weights", "redirects"):
        va = pa.get(key) if key != "window" else f"{a['window']['start']}..{a['window']['end']}"
        vb = pb.get(key) if key != "window" else f"{b['window']['start']}..{b['window']['end']}"
        if va != vb:
            out.append(f"changed {key}: {va} -> {vb}")
    la, lb = a["analysis"]["languages"], b["analysis"]["languages"]
    for lang in sorted(set(la) | set(lb)):
        ia, ib = la.get(lang), lb.get(lang)
        if ia is None:
            out.append(f"{lang}: added in B -> {_verdict(ib)}")
            continue
        if ib is None:
            out.append(f"{lang}: removed in B (was {_verdict(ia)})")
            continue
        va, vb = _verdict(ia), _verdict(ib)
        out.append(f"{lang}: {va} -> {vb}" + ("" if va != vb else " (unchanged)"))
    ra = [r["lang"] for r in a["analysis"].get("ranking", [])]
    rb = [r["lang"] for r in b["analysis"].get("ranking", [])]
    if ra != rb:
        out.append(f"ranking: {' > '.join(ra) or '-'} -> {' > '.join(rb) or '-'}")
    else:
        out.append(f"ranking unchanged: {' > '.join(rb) or '-'}")
    return out


def _verdict(info: dict) -> str:
    if info.get("status") != "ok":
        return "no article"
    m = info["metrics"]
    return (
        f"{info['direction']}, {info['confidence']} (share {fmt_pct(m['share_change'])}, "
        f"{fmt_int(m['avg_monthly_views_recent'])} views/mo)"
    )
