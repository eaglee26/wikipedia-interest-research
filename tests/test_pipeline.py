"""End-to-end tests of the CLI on real captured responses (no network)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import helpers
import wikitrends.net as net
from fakes import FakeWikimedia

WIKI = helpers.ROOT / "scripts" / "wiki.py"


def cli(*args, fake=None):
    """Run wiki.py main() in-process with the fake transport; return (exit, stdout)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("wiki_cli", WIKI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    original = net.urllib_transport
    net.urllib_transport = fake or FakeWikimedia()
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main(list(args))
    finally:
        net.urllib_transport = original
    return code, out.getvalue() + err.getvalue()


def pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except ImportError:
        data = path.read_bytes()
        return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["WIKI_RESEARCH_CACHE"] = str(self.tmp / "cache")
        self.out = str(self.tmp / "out")

    def test_example_1_polish_article_missing(self):
        code, text = cli("research", "--topics", "intermittent fasting", "--langs", "pl,cs", "--period", "24m", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("pl    NO DATA", text)
        self.assertIn("Q44602", text)  # proxy suggestion: fasting
        self.assertRegex(text, r"cs\s+\d+\s+-\d+\.\d%\s+-\d+\.\d%.*declining")
        run_dir = next((Path(self.out) / "runs").iterdir())
        summary = json.loads((run_dir / "summary.json").read_text())
        self.assertEqual(summary["analysis"]["languages"]["pl"]["status"], "no_data")
        for f in ("summary.json", "data_monthly.csv", "trend.png"):
            self.assertTrue((run_dir / f).exists(), f)

    def test_list_args_tolerate_spaces(self):
        # a free model wrote `--langs es, it` (argparse error before the fix)
        code, text = cli("research", "--topics", "intermittent", "fasting", "--langs", "pl,", "cs", "--period", "24m", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("pl    NO DATA", text)
        self.assertRegex(text, r"cs\s+\d+")

    def test_example_2_astronomy_uk_declines_with_school_seasonality(self):
        code, text = cli("research", "--topics", "астрономія", "--langs", "uk", "--period", "36m", "--ui", "uk", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("declining", text)
        self.assertIn("peaks in Sep", text)

    def test_repeat_run_uses_cache_only(self):
        fake = FakeWikimedia()
        cli("research", "--topics", "астрономія", "--langs", "uk", "--out", self.out, fake=fake)
        n = len(fake.calls)
        code, _ = cli("research", "--topics", "астрономія", "--langs", "uk", "--out", self.out, fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.calls), n)  # zero new requests

    def test_report_check_runs_diff_and_log(self):
        cli("research", "--topics", "астрономія", "--langs", "uk", "--period", "36m", "--out", self.out)
        summary = json.loads(next((Path(self.out) / "runs").glob("*/summary.json")).read_text())
        m = summary["analysis"]["languages"]["uk"]["metrics"]
        share = f"{abs(m['share_change']) * 100:.0f}%"
        narrative = {
            "language": "uk",
            "headline": "Інтерес до астрономії в україномовній Вікіпедії спадає",
            "answer": f"Частка переглядів упала на {share} за останні 12 місяців; довіра середня через невеликий трафік.",
            "recommendation": "Перевірити попит опитуванням перед запуском курсу.",
            "next_steps": ["Розширити кошик статей"],
        }
        npath = self.tmp / "n.json"
        npath.write_text(json.dumps(narrative, ensure_ascii=False))
        code, text = cli("report", "--run", "latest", "--narrative", str(npath), "--out", self.out)
        self.assertEqual(code, 0, text)
        pdf = Path(text.split("PDF ", 1)[1].splitlines()[0])
        self.assertEqual(pdf_pages(pdf), 1)

        bad = dict(narrative, answer="Частка переглядів упала на 73%.")
        npath.write_text(json.dumps(bad, ensure_ascii=False))
        code, text = cli("report", "--run", "latest", "--narrative", str(npath), "--out", self.out)
        self.assertEqual(code, 3)
        self.assertIn("73%", text)

        tpath = self.tmp / "answer.txt"
        tpath.write_text(f"Частка впала на {share}.", encoding="utf-8")
        self.assertEqual(cli("check", "--run", "latest", "--text", str(tpath), "--out", self.out)[0], 0)

        cli("research", "--topics", "астрономія", "--langs", "uk,cs", "--period", "36m", "--out", self.out)
        code, text = cli("runs", "--out", self.out)
        self.assertEqual(len([ln for ln in text.splitlines() if ln.startswith("- ")]), 2)
        rows = [json.loads(line) for line in (Path(self.out) / "runs.jsonl").read_text().splitlines()]
        code, text = cli("diff", rows[0]["run_id"], rows[1]["run_id"], "--out", self.out)
        self.assertEqual(code, 0)
        self.assertIn("changed langs", text)
        log = (Path(self.out) / ".log" / "commands.jsonl").read_text().splitlines()
        self.assertGreaterEqual(len(log), 4)

    def test_errors_have_distinct_exit_codes(self):
        self.assertEqual(cli("research", "--topics", "x", "--langs", "klingon!", "--out", self.out)[0], 2)
        self.assertEqual(cli("research", "--topics", "qwertyzzz", "--langs", "uk", "--out", self.out)[0], 5)
        self.assertEqual(cli("research", "--topics", "астрономія", "--langs", "xx", "--out", self.out)[0], 2)
        self.assertEqual(cli("report", "--run", "nope", "--narrative", "n.json", "--out", self.out)[0], 5)

    def test_ambiguous_topic_is_reported(self):
        code, text = cli("resolve", "--topics", "Mercury", "--langs", "cs,uk")
        self.assertEqual(code, 0)
        self.assertIn("Q308", text)
        self.assertIn("AMBIGUOUS", text)
        self.assertIn("Q925", text)


if __name__ == "__main__":
    unittest.main()
