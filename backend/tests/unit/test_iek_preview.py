from copy import deepcopy
from datetime import date
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.calculations.iek_preview import preview_iek, shipment_inputs
from app.modules.imports.adapters.common import SourceRow

ROOT = Path(__file__).resolve().parents[3]


class IekPreviewTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / "tests/fixtures/synthetic/iek_preview_policy.json").read_text(encoding="utf-8"))
        self.policy.update(calculation_date="2026-09-22", stock_mode="explicit_snapshot", service_z="0")
        self.policy["snapshots"] = {"001_": {"date": "2026-09-22", "storage_unit": "м", "available_stock": "0"}}
        self.policy["products"] = {"001_": {"storage_unit": "м", "order_unit": "бухта",
            "storage_units_per_order_unit": "100", "order_multiple": "2"}}
        def row(kind, fields):
            return SourceRow("fixture.xlsx", "hash", "iek", "Sheet", 2, kind, "001_", fields)
        self.sources = {
            "sales": [row("sales_monthly", {f"2026-{m:02d}-01": D(310) for m in range(1, 9)})],
            "inventory": [row("inventory_monthly", {"ед.": "м", "2026-09-01": D(9999)})],
            "constraints": [row("constraints", {"мин. разр. к отгр.": D(500)})],
            "inbound": [row("inbound", {"заказ 01.01.2026 (поступление до 30.09.2026)": D(10),
                "заказ 02.01.2026 (поступление до 30.09.2026)": D(20),
                "заказ 03.01.2026 (поступление до 13.10.2026)": D(9999)})]}
        self.sources["sales"][0].fields["2025-12-01"] = D(310)

    def run_preview(self):
        with TemporaryDirectory() as folder:
            return preview_iek(ROOT, self.policy, Path(folder) / "preview.json", self.sources)

    def test_reels_minimum_is_not_multiple_and_late_receipts_excluded(self):
        item = self.run_preview()["recommendations"][0]
        self.assertEqual(item["status"], "calculated")
        self.assertEqual(item["eligible_inbound"], D(30))
        self.assertEqual(item["order_quantity"], D(6))  # 500m MOQ -> 5 reels -> multiple 2
        self.assertEqual(item["first_deficit_date"], date(2026, 9, 22))
        self.assertEqual(item["urgency"], "expedite")
        self.assertEqual(len(item["inbound_inputs"]), 3)
        self.assertEqual(item["explanation_steps"][-2]["minimum"], D(5))

    def test_no_reel_length_inference_or_generic_metre_conversion(self):
        self.policy["unit_rules"]["м"] = self.policy["products"].pop("001_")
        item = self.run_preview()["recommendations"][0]
        self.assertEqual(item["status"], "insufficient_data")
        self.assertIsNone(item["order_quantity"])

    def test_current_stock_is_not_inferred_from_month_opening(self):
        self.policy["stock_mode"] = "unknown"
        self.assertEqual(self.run_preview()["recommendations"][0]["status"], "insufficient_data")
        self.policy["stock_mode"] = "historical_opening_proxy"
        item = self.run_preview()["recommendations"][0]
        self.assertEqual(item["order_quantity"], D(0))
        self.assertIn("Historical total", item["limitations"][-1])

    def test_snapshot_must_match_date_and_units(self):
        for field, bad in (("date", "2026-09-01"), ("storage_unit", "шт")):
            original = deepcopy(self.policy)
            self.policy["snapshots"]["001_"][field] = bad
            self.assertEqual(self.run_preview()["recommendations"][0]["status"], "insufficient_data")
            self.policy = original

    def test_missing_or_blank_inbound_requires_explicit_zero_policy(self):
        row = self.sources["inbound"][0]
        row.fields[next(iter(row.fields))] = None
        self.policy.pop("blank_inbound_quantity")
        with self.assertRaisesRegex(ValueError, "unknown"):
            shipment_inputs(row, self.policy)
        self.policy.pop("missing_inbound_row")
        with self.assertRaisesRegex(ValueError, "missing"):
            shipment_inputs(None, self.policy)
        self.policy["assume_inbound_confirmed"] = False
        row.fields[next(iter(row.fields))] = D(10)
        self.assertEqual(self.run_preview()["recommendations"][0]["eligible_inbound"], D(0))

    def test_duplicate_constraints_block_ambiguous_join(self):
        self.sources["constraints"] *= 2
        self.assertIn("ambiguous", self.run_preview()["recommendations"][0]["limitations"][0])

    def test_bad_arrival_or_negative_quantity_blocks(self):
        row = self.sources["inbound"][0]
        row.fields.clear()
        row.fields["поступление до неизвестно"] = D(1)
        with self.assertRaises(ValueError):
            shipment_inputs(row, self.policy)
        row.fields.clear()
        row.fields["поступление до 30.09.2026"] = D(-1)
        with self.assertRaises(ValueError):
            shipment_inputs(row, self.policy)

    def test_unknown_constraint_is_not_assumed_zero(self):
        self.sources["constraints"] = []
        item = self.run_preview()["recommendations"][0]
        self.assertEqual(item["status"], "insufficient_data")
        self.assertIsNone(item["order_quantity"])
