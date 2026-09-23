from datetime import date
from decimal import Decimal as D
import unittest

from app.engine.forecast import baseline_daily


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.history = {date(2026, m, 1): D(days * 10) for m, days in ((3, 31), (4, 30), (5, 31), (6, 30), (7, 31), (8, 31))}

    def test_uses_daily_rates_and_excludes_partial_month_and_future(self):
        self.history[date(2026, 9, 1)] = D(999999)
        self.history[date(2026, 10, 1)] = D(999999)
        self.assertEqual(baseline_daily(self.history, date(2026, 9, 22), 3), (D(10),) * 3)

    def test_unknown_month_is_not_zero_or_skipped(self):
        self.history[date(2026, 7, 1)] = None
        with self.assertRaises(ValueError):
            baseline_daily(self.history, date(2026, 9, 22), 3)

    def test_negative_month_requires_review(self):
        self.history[date(2026, 7, 1)] = D(-100)
        with self.assertRaises(ValueError):
            baseline_daily(self.history, date(2026, 9, 22), 3)


if __name__ == "__main__":
    unittest.main()
