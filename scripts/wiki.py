#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy>=1.26,<3",
#   "matplotlib>=3.8,<4",
#   "certifi>=2024.2.2",
# ]
# ///
"""Wikipedia interest research CLI (the Agent Skill's single entry point).

Run with uv (dependencies install automatically):
  uv run <SKILL_DIR>/scripts/wiki.py research --topics "astronomy" --langs uk --period 36m --ui uk
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

# Keep matplotlib's font cache out of read-only home directories (sandboxed agents).
if "MPLCONFIGDIR" not in os.environ:
    _mpl = Path(os.environ.get("WIKI_RESEARCH_CACHE") or Path.home() / ".cache" / "wikipedia-interest-research") / "mpl"
    try:
        _mpl.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(_mpl)
    except OSError:
        pass

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INVALID, EXIT_NETWORK, EXIT_NOT_FOUND = 0, 1, 2, 3, 4, 5

try:
    import matplotlib  # noqa: F401
    import numpy  # noqa: F401
except ImportError as _e:  # pragma: no cover - depends on environment
    print(
        f"Missing dependency ({_e.name}). Run through uv, which installs everything automatically:\n"
        f"  uv run {SKILL_DIR}/scripts/wiki.py <command> ...\n"
        f"or install once with pip:\n"
        f"  python3 -m pip install -r {SKILL_DIR}/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(EXIT_USAGE)

from wikitrends import config, output, runs  # noqa: E402
from wikitrends.net import HttpError, NetworkBlocked  # noqa: E402
from wikitrends.pipeline import ResearchParams, UsageError, log_command, parse_weights, run_research  # noqa: E402
from wikitrends.resolve import ResolveError, split_topics  # noqa: E402

EPILOG = """exit codes: 0 ok, 2 bad arguments (message says how to fix), 3 text/report failed validation,
4 cannot reach Wikimedia, 5 topic or run not found, 1 unexpected error

examples:
  wiki.py research --topics "intermittent fasting" --langs pl,cs --period 24m
  wiki.py research --topics "astronomy, Solar System, black hole, telescope, galaxy" --langs uk --period 36m --ui uk
  wiki.py research --topics "English language, English grammar, IELTS" --langs pl,tr,vi,id --weights growth=0.5,volume=0.3,reliability=0.2
  wiki.py resolve --topics "Mercury" --langs pl,cs
  wiki.py report --run latest --narrative narrative.json --ui uk
  wiki.py check --run latest --text answer.md
  wiki.py runs
  wiki.py diff <run_a> <run_b>
"""


def _out_dir(args) -> Path:
    return Path(args.out).expanduser() if getattr(args, "out", None) else config.default_out_dir()


def cmd_research(args) -> tuple[int, str | None]:
    params = ResearchParams(
        topics=split_topics(args.topics) if args.topics else [],
        qids=[q.strip() for q in (args.qids or "").split(",") if q.strip()],
        langs=args.langs,
        period=args.period,
        start=args.start,
        end=args.end,
        search_lang=args.search_lang,
        weights=parse_weights(args.weights),
        exclude=[e for e in (args.exclude or "").split(",") if e.strip()],
        redirects=args.redirects,
        ui=args.ui,
        out_dir=_out_dir(args),
        offline=args.offline,
        charts=not args.no_charts,
    )
    summary, _path = run_research(params)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        print(output.render_research(summary, str(SKILL_DIR)))
    return EXIT_OK, summary["run_id"]


def cmd_resolve(args) -> tuple[int, str | None]:
    from wikitrends.cache import Cache
    from wikitrends.languages import normalize_langs
    from wikitrends.net import HttpClient
    from wikitrends.resolve import resolve_topics

    lc = normalize_langs(args.langs)
    if lc.errors:
        raise UsageError(" ".join(lc.errors))
    cache = Cache()
    concepts, notes = resolve_topics(
        HttpClient(), cache, split_topics(args.topics or ""), lc.codes, args.search_lang,
        [q.strip() for q in (args.qids or "").split(",") if q.strip()],
    )
    cache.close()
    print(output.render_resolve(concepts, lc.codes, lc.notes + notes))
    return EXIT_OK, None


def cmd_report(args) -> tuple[int, str | None]:
    from wikitrends import report

    run_path = runs.resolve_run(_out_dir(args), args.run)
    summary = runs.load_summary(run_path)
    narrative = report.load_narrative(Path(args.narrative))
    ui = args.ui or narrative.get("language") or summary["params"].get("ui", "en")
    errors, warnings = report.validate_narrative(narrative, summary)
    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        print("REPORT NOT BUILT — fix the narrative and run the same command again:")
        for e in errors:
            print(f"  - {e}")
        return EXIT_INVALID, summary["run_id"]
    out = Path(args.output) if args.output else run_path / f"report_{ui}.pdf"
    try:
        report.build_pdf(summary, narrative, out, ui)
    except report.ReportError as e:
        print("REPORT NOT BUILT:")
        for err in e.errors:
            print(f"  - {err}")
        return EXIT_INVALID, summary["run_id"]
    print(f"PDF {out.resolve()}")
    print("One A4 page: answer (yours), numbers table, charts, confidence reasons, limitations, sources (generated).")
    print("Share this file with the user.")
    return EXIT_OK, summary["run_id"]


def cmd_check(args) -> tuple[int, str | None]:
    from wikitrends.textcheck import check_text

    run_path = runs.resolve_run(_out_dir(args), args.run)
    summary = runs.load_summary(run_path)
    text = sys.stdin.read() if args.text == "-" else Path(args.text).read_text(encoding="utf-8")
    res = check_text(text, summary)
    for w in res.warnings:
        print(f"WARNING: {w}")
    if res.errors:
        print(f"CHECK FAILED ({len(res.errors)} problem(s), {res.checked} numbers checked):")
        for e in res.errors:
            print(f"  - {e}")
        return EXIT_INVALID, summary["run_id"]
    print(f"CHECK OK: {res.checked} numbers match run {summary['run_id']}.")
    return EXIT_OK, summary["run_id"]


def cmd_runs(args) -> tuple[int, str | None]:
    print(output.render_runs(runs.list_runs(_out_dir(args), args.limit)))
    return EXIT_OK, None


def cmd_diff(args) -> tuple[int, str | None]:
    out_dir = _out_dir(args)
    a = runs.load_summary(runs.resolve_run(out_dir, args.run_a))
    b = runs.load_summary(runs.resolve_run(out_dir, args.run_b))
    print("\n".join(runs.diff_runs(a, b)))
    return EXIT_OK, None


def cmd_doctor(args) -> tuple[int, str | None]:
    import platform

    import matplotlib as mpl
    import numpy as np

    from wikitrends.cache import Cache
    from wikitrends.net import HttpClient

    ok = True
    print(f"python {platform.python_version()} ({sys.executable})")
    if sys.version_info < (3, 10):  # noqa: UP036 - users may run it with an old system python
        print("FAIL python >= 3.10 required (uv installs it automatically: uv run ...)")
        ok = False
    print(f"numpy {np.__version__} · matplotlib {mpl.__version__}")
    try:
        c = Cache()
        c.close()
        print(f"OK cache {config.cache_dir()}")
    except OSError as e:
        print(f"FAIL cache dir not writable ({e}); set WIKI_RESEARCH_CACHE to a writable folder")
        ok = False
    ua = config.user_agent()
    print(f"user-agent {ua}")
    if "REPLACE_ME" in ua:
        print("WARN set WIKI_RESEARCH_CONTACT to your repo URL or email (Wikimedia User-Agent policy)")
    client = HttpClient(retries=1)
    for name, url in (
        ("pageviews", f"{config.PAGEVIEWS_BASE}/aggregate/en.wikipedia/all-access/user/monthly/20240101/20240131"),
        ("wikidata", f"{config.WIKIDATA_API}?action=wbgetentities&ids=Q42&props=info&format=json"),
    ):
        try:
            client.get_json(url)
            print(f"OK network {name}")
        except (HttpError, NetworkBlocked) as e:
            print(f"FAIL network {name}: {e}")
            ok = False
    print("READY" if ok else "NOT READY")
    return (EXIT_OK if ok else EXIT_NETWORK), None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wiki.py",
        description="Measure how interest in topics changes across Wikipedia language editions (Wikimedia pageviews).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    sub = p.add_subparsers(dest="command", required=True)

    class Joined(argparse.Action):
        """Accept both `--langs pl,cs` and `--langs pl, cs` / `--langs pl cs` (cheap models vary)."""

        def __init__(self, *a, sep: str = ",", **kw):
            self.sep = sep
            super().__init__(*a, nargs="+", **kw)

        def __call__(self, parser, namespace, values, option_string=None):
            parts = [v.strip().strip(",;").strip() for v in values]
            setattr(namespace, self.dest, self.sep.join(x for x in parts if x) if self.sep != " " else " ".join(v.strip() for v in values))

    def common(sp):
        sp.add_argument("--out", help="output folder for runs (default: ./wiki-research)")

    r = sub.add_parser("research", help="resolve topics, fetch pageviews, analyse, save a run", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG)
    r.add_argument("--topics", action=Joined, sep=" ", help='comma-separated topic names in any language, e.g. "astronomy, black hole"')
    r.add_argument("--qids", action=Joined, help="comma-separated Wikidata ids to use as-is, e.g. Q308,Q925")
    r.add_argument("--langs", action=Joined, required=True, help="comma-separated Wikipedia language codes, e.g. pl,cs,uk")
    r.add_argument("--period", default=None, help="last N complete months: 24m (default), 36m, 5y")
    r.add_argument("--start", help="first month YYYY-MM (instead of --period)")
    r.add_argument("--end", help="last month YYYY-MM (default: last complete month)")
    r.add_argument("--weights", help="ranking weights, e.g. growth=0.5,volume=0.3,reliability=0.2")
    r.add_argument("--exclude", action=Joined, help="comma-separated topics/QIDs to drop from the basket")
    r.add_argument("--search-lang", help="language of the topic names (auto by default)")
    r.add_argument("--redirects", choices=["auto", "all", "none"], default="auto",
                   help="add views of redirect titles: auto = only for renamed/late-starting articles")
    r.add_argument("--ui", choices=["en", "uk"], default="en", help="language of chart labels")
    r.add_argument("--format", choices=["text", "json"], default="text")
    r.add_argument("--no-charts", action="store_true")
    r.add_argument("--offline", action="store_true", help="use cached data only")
    common(r)
    r.set_defaults(func=cmd_research)

    s = sub.add_parser("resolve", help="show which article represents each topic in each language (no pageviews)")
    s.add_argument("--topics", action=Joined, sep=" ", default="")
    s.add_argument("--qids", action=Joined)
    s.add_argument("--langs", action=Joined, required=True)
    s.add_argument("--search-lang")
    s.set_defaults(func=cmd_resolve)

    rp = sub.add_parser("report", help="build a one-page PDF for a run from a narrative JSON")
    rp.add_argument("--run", default="latest", help="run id (or 'latest')")
    rp.add_argument("--narrative", required=True, help="JSON file based on assets/narrative.template.json")
    rp.add_argument("--ui", choices=["en", "uk"], help="report language (default: narrative.language)")
    rp.add_argument("--output", help="PDF path (default: <run folder>/report_<ui>.pdf)")
    common(rp)
    rp.set_defaults(func=cmd_report)

    c = sub.add_parser("check", help="verify the numbers in a text answer against a run")
    c.add_argument("--run", default="latest")
    c.add_argument("--text", required=True, help="file with the answer text, or - for stdin")
    common(c)
    c.set_defaults(func=cmd_check)

    ls = sub.add_parser("runs", help="list recent runs")
    ls.add_argument("--limit", type=int, default=10)
    common(ls)
    ls.set_defaults(func=cmd_runs)

    d = sub.add_parser("diff", help="compare two runs (what changed after a follow-up)")
    d.add_argument("run_a")
    d.add_argument("run_b")
    common(d)
    d.set_defaults(func=cmd_diff)

    doc = sub.add_parser("doctor", help="check Python, dependencies, cache and network access")
    doc.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    run_id = None
    try:
        status, run_id = args.func(args)
    except UsageError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        status = EXIT_USAGE
    except ResolveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        status = EXIT_NOT_FOUND
    except runs.RunNotFound as e:
        print(f"ERROR: {e}", file=sys.stderr)
        status = EXIT_NOT_FOUND
    except NetworkBlocked as e:
        print(f"ERROR: {e}", file=sys.stderr)
        status = EXIT_NETWORK
    except HttpError as e:
        print(f"ERROR: Wikimedia API error: {e}", file=sys.stderr)
        status = EXIT_NETWORK
    if args.command in ("research", "report", "check"):
        log_command(_out_dir(args), [args.command, *argv[1:]], status, run_id)
    return status


if __name__ == "__main__":
    sys.exit(main())
