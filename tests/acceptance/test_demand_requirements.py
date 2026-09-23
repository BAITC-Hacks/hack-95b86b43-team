"""Numerical must-have checks. Approval/export UI is deliberately outside this suite."""
import csv
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.engine.contracts import Inbound
from app.engine.forecast import robust_daily
from app.engine.outliers import detect_outliers
from app.engine.pipeline import prepare_demand, recommend, CategoryPolicy
from app.modules.calculations.synthetic import (monthly_fixture, transaction_fixture, replenishment_fixture,
                                               START, AS_OF, run_demo)


class DemandRequirements(unittest.TestCase):
    def test_history_stock_inbound_category_external_growth_each_affect_raw_requirement(self):
        history = monthly_fixture(noisy=True)
        inputs = replace(replenishment_fixture(), available_stock=D(0), inbound=())
        policy = CategoryPolicy("test", D(1))
        base = recommend(history, inputs, policy).replenishment
        variants = (
            recommend({m: q * 2 for m, q in history.items()}, inputs, policy),
            recommend(history, replace(inputs, available_stock=D(10)), policy),
            recommend(history, replace(inputs, inbound=(Inbound(date(2026, 1, 5), D(10)),)), policy),
            recommend(history, inputs, CategoryPolicy("higher", D(2))),
            recommend(history, inputs, policy, D("0.2"), "additional"),
        )
        for value in variants:
            self.assertNotEqual(value.replenishment.raw_requirement, base.raw_requirement)
            self.assertNotEqual(value.replenishment.order_quantity, base.order_quantity)

    def test_seasonality_and_sustained_growth(self):
        seasonal = robust_daily(monthly_fixture(seasonal=True), AS_OF, 220)
        self.assertGreater(seasonal.daily[181], seasonal.daily[0] * 2)
        growth = robust_daily(monthly_fixture(growth=D("1.02")), AS_OF, 30)
        self.assertGreater(sum(growth.daily), sum(robust_daily(monthly_fixture(), AS_OF, 30).daily))

    def test_confirmed_stockout_increases_demand_and_order(self):
        sales, intervals, _ = transaction_fixture("stockout")
        raw = prepare_demand(sales, START, AS_OF, D(100), frozenset(), coverage_complete=True)
        restored = prepare_demand(sales, START, AS_OF, D(100), frozenset(), intervals, coverage_complete=True)
        self.assertEqual(sum(restored.stockouts.added.values()), D(297))
        inputs = replace(replenishment_fixture(), available_stock=D(0), inbound=())
        category = CategoryPolicy("test", D(0))
        raw_order = recommend(raw.monthly, inputs, category)
        fixed_order = recommend(restored.monthly, inputs, category)
        self.assertGreater(sum(fixed_order.forecast.daily), sum(raw_order.forecast.daily))
        self.assertGreater(fixed_order.replenishment.order_quantity, raw_order.replenishment.order_quantity)
        covered = recommend(restored.monthly, replace(inputs, available_stock=D(10000)), category)
        self.assertEqual(covered.replenishment.order_quantity, 0)

    def test_confirmed_20x_document_and_split_order_change_forecast_at_most_five_percent(self):
        reference = sum(robust_daily(monthly_fixture(), AS_OF, 21).daily)
        for kind in ("outlier_document", "outlier_split"):
            sales, _, project_docs = transaction_fixture(kind)
            candidates = detect_outliers(sales, AS_OF, D(100)).candidates
            self.assertEqual(len(candidates), 1)
            self.assertEqual(set(candidates[0].documents), project_docs)
            confirmed = frozenset(c.id for c in candidates)
            prepared = prepare_demand(sales, START, AS_OF, D(100), confirmed, coverage_complete=True)
            self.assertEqual(prepared.excluded_quantity, D(200))
            actual = sum(robust_daily(prepared.monthly, AS_OF, 21).daily)
            self.assertLessEqual(abs(actual / reference - 1), D("0.05"))

    def test_supplier_grouping_explanation_and_diagnostic_csv_agree(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "demo.json"
            result = run_demo(path)
            before = path.read_bytes()
            run_demo(path)
            self.assertEqual(before, path.read_bytes())
            with path.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 9)
            self.assertEqual([r["supplier"] for r in rows], sorted(r["supplier"] for r in rows))
            for row, recommendation in zip(rows, result["recommendations"]):
                self.assertEqual(D(row["order_quantity"]), recommendation["order_quantity"])
                explanation = json.loads(row["explanation"])
                self.assertEqual(explanation[-1]["operation"], "order_quantity")
                self.assertEqual(D(explanation[-1]["value"]), D(row["order_quantity"]))
                arithmetic = next(s for s in explanation if s["operation"] == "max_zero_demand_plus_safety_minus_stock_minus_inbound")
                self.assertEqual(D(arithmetic["value"]), max(D(0), D(arithmetic["demand"]) + D(arithmetic["safety_stock"])
                                                           - D(arithmetic["available_stock"]) - D(arithmetic["inbound"])))
            late = next(r for r in result["recommendations"] if r["code"] == "late_inbound")
            self.assertEqual(late["order_quantity"], 0)
            self.assertEqual(late["urgency"], "expedite")


if __name__ == "__main__":
    unittest.main()
