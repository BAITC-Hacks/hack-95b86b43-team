from calendar import monthrange
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
import unittest

from app.engine.forecast import robust_daily, shift_month, backtest_monthly, error_safety_stock, ALGORITHM_VERSION
from app.engine.outliers import Sale, detect_outliers, cleaned_daily
from app.engine.stockouts import StockoutInterval, restore_stockouts, daily_to_monthly
from app.engine.pipeline import prepare_demand, recommend, CategoryPolicy
from app.engine.contracts import ReplenishmentInput, Inbound

AS_OF = date(2026, 1, 1)
PROFILE = tuple(map(D, ("0.6", "0.6", "0.8", "1", "1.2", "1.4", "1.6", "1.4", "1.2", "1", "0.7", "0.5")))


def monthly(count=36, seasonal=False, growth=D(1)):
    result = {}
    for i in range(count):
        period = shift_month(AS_OF, i - count)
        daily = D(10) * growth ** i * (PROFILE[period.month - 1] if seasonal else 1)
        result[period] = daily * monthrange(period.year, period.month)[1]
    return result


class ForecastModelTests(unittest.TestCase):
    def test_recurring_seasonality_and_daily_calendar(self):
        prediction = robust_daily(monthly(seasonal=True), AS_OF, 220)
        self.assertAlmostEqual(prediction.daily[0], D(6))
        self.assertAlmostEqual(prediction.daily[181], D(16))
        self.assertAlmostEqual(sum(prediction.seasonal_indices), D(12))

    def test_sustained_growth_but_not_single_peak(self):
        growing = robust_daily(monthly(growth=D("1.02")), AS_OF, 10)
        self.assertGreater(growing.monthly_trend, D("1.015"))
        self.assertLessEqual(growing.monthly_trend, D("1.05"))
        history = monthly()
        history[date(2025, 12, 1)] *= 20
        peak = robust_daily(history, AS_OF, 10)
        self.assertEqual(peak.monthly_trend, D(1))
        self.assertLessEqual(abs(sum(peak.daily) / D(100) - 1), D("0.05"))

    def test_two_cycle_isolated_spike_does_not_become_seasonality(self):
        history = monthly(24)
        history[date(2025, 1, 1)] *= 20
        prediction = robust_daily(history, AS_OF, 10)
        self.assertLessEqual(abs(sum(prediction.daily) / 100 - 1), D("0.05"))

    def test_detrends_before_estimating_seasonality(self):
        forecast = robust_daily(monthly(seasonal=True, growth=D("1.02")), AS_OF, 10)
        self.assertAlmostEqual(forecast.seasonal_indices[0], PROFILE[0], places=8)
        self.assertAlmostEqual(forecast.monthly_trend, D("1.02"), places=8)

    def test_growth_replacement_is_not_double_counted(self):
        history = monthly(growth=D("1.02"))
        replacement = robust_daily(history, AS_OF, 10, D("0.2"), "replace")
        additional = robust_daily(history, AS_OF, 10, D("0.2"), "additional")
        self.assertAlmostEqual(sum(additional.daily) / sum(replacement.daily), D("1.02"), places=8)
        with self.assertRaises(ValueError):
            robust_daily(history, AS_OF, 10, D("0.2"))

    def test_partial_month_and_future_have_no_effect(self):
        history = monthly()
        expected = robust_daily(history, date(2026, 1, 15), 20)
        history[date(2026, 1, 1)] = D(9999999)
        history[date(2026, 2, 1)] = D(9999999)
        self.assertEqual(robust_daily(history, date(2026, 1, 15), 20), expected)

    def test_missing_recent_month_blocks_older_gap_limits_window(self):
        history = monthly()
        history[date(2025, 1, 1)] = None
        result = robust_daily(history, AS_OF, 10)
        self.assertEqual(result.history_months, 11)
        self.assertTrue(result.limitations)
        history[date(2025, 12, 1)] = None
        with self.assertRaises(ValueError):
            robust_daily(history, AS_OF, 10)

    def test_intermittent_and_zero_demand(self):
        history = {p: D(0) for p in monthly()}
        self.assertEqual(sum(robust_daily(history, AS_OF, 30).daily), 0)
        history[date(2025, 12, 1)] = D(31)
        forecast = robust_daily(history, AS_OF, 12)
        self.assertEqual(forecast.method, "intermittent_frequency_size")
        self.assertAlmostEqual(sum(forecast.daily), D(1))

    def test_explicit_seasonal_fallback_and_invalid_inputs(self):
        forecast = robust_daily(monthly(6), AS_OF, 10, fallback_seasonality=PROFILE)
        self.assertAlmostEqual(forecast.seasonal_indices[0], D("0.6"))
        for kwargs in ({"external_growth": D("NaN"), "growth_mode": "replace"},
                       {"external_growth": D(-2), "growth_mode": "replace"},
                       {"fallback_seasonality": (D(0),) * 12}):
            with self.assertRaises(ValueError):
                robust_daily(monthly(), AS_OF, 10, **kwargs)

    def test_backtest_is_past_only_and_reports_zero_denominator(self):
        history = monthly(seasonal=True)
        metrics = backtest_monthly(history, AS_OF)
        self.assertEqual(metrics[ALGORITHM_VERSION]["origins"], 6)
        self.assertLess(metrics[ALGORITHM_VERSION]["mae"], D("0.000001"))
        history[AS_OF] = D(999999)
        self.assertEqual(metrics, backtest_monthly(history, AS_OF))
        zeros = backtest_monthly({p: D(0) for p in history}, AS_OF)
        self.assertIsNone(zeros[ALGORITHM_VERSION]["wape"])
        with self.assertRaises(ValueError):
            error_safety_stock(backtest_monthly(monthly(6), AS_OF)[ALGORITHM_VERSION], 10, D(1))


class OutlierTests(unittest.TestCase):
    def setUp(self):
        self.start = date(2025, 1, 1)
        self.sales = tuple(Sale(self.start + timedelta(days=i), f"ordinary-{i}", D(10), "SKU", "total") for i in range(90))
        self.as_of = self.start + timedelta(days=90)

    def test_document_20x_aggregates_lines_and_requires_confirmation(self):
        sales = self.sales + tuple(Sale(date(2025, 2, 15), "project", D(100), "SKU", "total") for _ in range(2))
        detection = detect_outliers(sales, self.as_of, D(100))
        self.assertEqual(len(detection.candidates), 1)
        self.assertEqual(detection.candidates[0].quantity, D(200))
        unconfirmed, volume = cleaned_daily(sales, self.start, self.as_of, detection, frozenset(), coverage_complete=True)
        self.assertEqual(volume, 0)
        confirmed, volume = cleaned_daily(sales, self.start, self.as_of, detection,
            frozenset(c.id for c in detection.candidates), coverage_complete=True)
        self.assertEqual(volume, D(200))
        self.assertEqual(sum(confirmed.values()), D(900))
        self.assertEqual(sum(unconfirmed.values()), D(1100))

    def test_split_client_order_is_found(self):
        sales = self.sales + tuple(Sale(date(2025, 2, 15), f"part-{i}", D(40), "SKU", "total", "anon-project") for i in range(5))
        detection = detect_outliers(sales, self.as_of, D(100))
        self.assertEqual(len(detection.candidates), 1)
        self.assertEqual(len(detection.candidates[0].documents), 5)

    def test_changed_source_invalidates_confirmation(self):
        project = Sale(date(2025, 2, 15), "project", D(200), "SKU", "total")
        old = detect_outliers(self.sales + (project,), self.as_of, D(100))
        changed_sales = self.sales + (replace(project, quantity=D(300)),)
        new = detect_outliers(changed_sales, self.as_of, D(100))
        self.assertNotEqual(old.candidates[0].id, new.candidates[0].id)
        with self.assertRaises(ValueError):
            cleaned_daily(changed_sales, self.start, self.as_of, new,
                          frozenset(c.id for c in old.candidates), coverage_complete=True)

    def test_regular_large_client_is_preserved(self):
        sales = self.sales + tuple(Sale(date(2025, m, 15), f"regular-{m}", D(200), "SKU", "total", "anon-regular") for m in (1, 2, 3))
        result = detect_outliers(sales, self.as_of, D(100))
        self.assertFalse(result.candidates)
        self.assertEqual(len(result.protected_documents), 3)

    def test_sustained_new_level_is_preserved(self):
        sales = tuple(s for s in self.sales if s.day < date(2025, 3, 1)) + tuple(
            Sale(date(2025, 3, 1) + timedelta(days=i * 5), f"new-{i}", D(200), "SKU", "total") for i in range(5))
        self.assertFalse(detect_outliers(sales, self.as_of, D(100)).candidates)

    def test_future_returns_and_scope(self):
        future = Sale(self.as_of, "future", D(9999), "SKU", "total")
        self.assertFalse(detect_outliers(self.sales + (future,), self.as_of, D(100)).candidates)
        with self.assertRaises(ValueError):
            detect_outliers(self.sales + (replace(self.sales[0], quantity=D(-1)),), self.as_of, D(100))
        with self.assertRaises(ValueError):
            detect_outliers(self.sales + (replace(self.sales[0], warehouse="other"),), self.as_of, D(100))
        with self.assertRaises(ValueError):
            cleaned_daily(self.sales, self.start, self.as_of, detect_outliers(self.sales, self.as_of, D(100)), frozenset(), coverage_complete=False)


class StockoutTests(unittest.TestCase):
    def setUp(self):
        self.start = date(2025, 1, 1)
        self.daily = {self.start + timedelta(days=i): D(10) for i in range(90)}
        self.day = date(2025, 3, 1)
        self.end = date(2025, 4, 1)

    def test_overlap_and_observed_sales_are_not_double_counted(self):
        self.daily[self.day] = D(3)
        interval = StockoutInterval(self.day, self.day + timedelta(days=1))
        result = restore_stockouts(self.daily, (interval, interval), self.end)
        self.assertEqual(result.added[self.day], D(7))
        self.assertEqual(result.daily[self.day], D(10))

    def test_unconfirmed_or_monthly_snapshot_does_not_prove_absence(self):
        self.daily[self.day] = D(0)
        result = restore_stockouts(self.daily, (StockoutInterval(self.day, self.end, False),), self.end)
        self.assertFalse(result.added)
        self.assertEqual(result.daily[self.day], 0)

    def test_weights_and_no_future_peers(self):
        self.daily[self.day] = D(0)
        weights = {day: D(1) for day in self.daily}
        weights[self.day] = D(2)
        result = restore_stockouts(self.daily, (StockoutInterval(self.day, self.day + timedelta(days=1)),), self.end, weights)
        self.assertEqual(result.added[self.day], D(20))
        short = {self.start + timedelta(days=i): D(999) for i in range(15)}
        short[self.start] = D(0)
        result = restore_stockouts(short, (StockoutInterval(self.start, self.start + timedelta(days=1)),), self.end)
        self.assertEqual(result.unresolved_days, (self.start,))

    def test_unknown_sales_not_assumed_zero_and_explicit_fallback(self):
        interval = StockoutInterval(self.start, self.start + timedelta(days=1))
        result = restore_stockouts({self.start: D(0)}, (interval,), self.end, category_daily=D(5))
        self.assertEqual(result.added[self.start], D(5))
        result = restore_stockouts({self.start: None}, (interval,), self.end, category_daily=D(5))
        self.assertEqual(result.unresolved_days, (self.start,))

    def test_monthly_aggregation_requires_every_day(self):
        self.assertEqual(daily_to_monthly(self.daily, self.end)[date(2025, 1, 1)], D(310))
        del self.daily[self.start]
        self.assertIsNone(daily_to_monthly(self.daily, self.end)[date(2025, 1, 1)])


if __name__ == "__main__":
    unittest.main()
