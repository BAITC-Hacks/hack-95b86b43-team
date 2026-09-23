from datetime import date
from decimal import Decimal as D, ROUND_CEILING
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.calculations.preview import preview
from app.modules.imports.adapters.common import file_hash

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless((ROOT / "Systeme electric").exists(), "Partner workbooks are not present")
class SystemePreviewTests(unittest.TestCase):
    def test_real_sources_provenance_arithmetic_and_repeatability(self):
        policy = json.loads((ROOT / "tests/fixtures/synthetic/systeme_preview_policy.json").read_text(encoding="utf-8"))
        sources = list((ROOT / "Systeme electric").glob("*.xlsx"))
        original_hashes = {p: file_hash(p) for p in sources}
        with TemporaryDirectory() as folder:
            output = Path(folder) / "preview.json"
            result = preview(ROOT, policy, output)
            first = output.read_bytes()
            preview(ROOT, policy, output)
            self.assertEqual(first, output.read_bytes())
            self.assertIn("не утверждённый заказ", output.with_suffix(".html").read_text(encoding="utf-8"))
        self.assertGreater(len(result["recommendations"]), 0)
        statuses = set()
        for item in result["recommendations"]:
            statuses.add(item["status"])
            self.assertIn(item["source"]["sha256"], original_hashes.values())
            if item["status"] != "calculated":
                self.assertIsNone(item["order_quantity"])
                self.assertTrue(item["limitations"])
                continue
            steps = {s["operation"]: s for s in item["explanation_steps"]}
            arithmetic = steps["max_zero_demand_plus_safety_minus_stock_minus_inbound"]
            expected = max(D(0), arithmetic["demand"] + arithmetic["safety_stock"]
                           - arithmetic["available_stock"] - arithmetic["inbound"])
            self.assertEqual(expected, item["raw_requirement"])
            if expected > 0:
                rounding = steps["convert_apply_minimum_round_up"]
                minimum = max(expected / rounding["conversion"], rounding["minimum"])
                expected_order = (minimum / rounding["multiple"]).to_integral_value(rounding=ROUND_CEILING) * rounding["multiple"]
                self.assertEqual(expected_order, item["order_quantity"])
            else:
                self.assertEqual(item["order_quantity"], 0)
        self.assertEqual(statuses, {"calculated", "insufficient_data"})
        self.assertEqual(original_hashes, {p: file_hash(p) for p in sources})


if __name__ == "__main__":
    unittest.main()
