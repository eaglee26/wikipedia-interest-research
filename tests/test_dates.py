import unittest
from datetime import date

import helpers  # noqa: F401
from wikitrends.dates import PeriodError, last_complete_month, make_window, parse_period


class TestDates(unittest.TestCase):
    def test_last_complete_month_respects_publication_lag(self):
        self.assertEqual(last_complete_month(date(2026, 9, 27)), (2026, 8))
        self.assertEqual(last_complete_month(date(2026, 10, 1)), (2026, 8))  # Sep 30 not safely published
        self.assertEqual(last_complete_month(date(2026, 10, 2)), (2026, 9))
        self.assertEqual(last_complete_month(date(2026, 1, 1)), (2025, 11))

    def test_parse_period(self):
        self.assertEqual(parse_period("24m"), 24)
        self.assertEqual(parse_period("2y"), 24)
        self.assertEqual(parse_period("36"), 36)
        self.assertEqual(parse_period("18 months"), 18)
        with self.assertRaises(PeriodError):
            parse_period("two years")
        with self.assertRaises(PeriodError):
            parse_period("2m")

    def test_window_from_period(self):
        w = make_window("24m", today=date(2026, 9, 27))
        self.assertEqual(w.months[0], "2024-09")
        self.assertEqual(w.months[-1], "2026-08")
        self.assertEqual(w.start_day, "20240901")
        self.assertEqual(w.end_day, "20260831")
        self.assertEqual(len(w.days()), 730)

    def test_window_errors(self):
        with self.assertRaises(PeriodError):
            make_window(end="2026-09", today=date(2026, 9, 27))  # not complete yet
        with self.assertRaises(PeriodError):
            make_window(start="2014-01", end="2015-12", today=date(2026, 9, 27))  # before data starts
        with self.assertRaises(PeriodError):
            make_window(start="2026-07", end="2026-08", today=date(2026, 9, 27))  # < 3 months


if __name__ == "__main__":
    unittest.main()
