from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.calculations.iek_preview import preview_iek
from app.modules.imports.adapters.common import file_hash

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless((ROOT / "IEK").is_dir(), "Real IEK sources unavailable")
class IekFilePreviewTests(unittest.TestCase):
    def test_real_sources_are_unchanged_and_each_quantity_is_explained(self):
        files = list((ROOT / "IEK").glob("*.xlsx"))
        before = {p: file_hash(p) for p in files}
        policy = json.loads((ROOT / "tests/fixtures/synthetic/iek_preview_policy.json").read_text(encoding="utf-8"))
        with TemporaryDirectory() as folder:
            output = Path(folder) / "iek.json"
            result = preview_iek(ROOT, policy, output)
            self.assertEqual(len(result["recommendations"]), 2463)
            self.assertGreater(Counter(r["status"] for r in result["recommendations"])["calculated"], 0)
            for item in result["recommendations"]:
                if item["status"] == "calculated":
                    self.assertEqual(item["explanation_steps"][-1]["value"], item["order_quantity"])
                    if item["order_quantity"] > 0:
                        self.assertIn(item["storage_unit"], {"шт", "шт."})
                    self.assertIn("stock_input", item)
            self.assertIn("Historical total", output.with_suffix(".html").read_text(encoding="utf-8"))
        self.assertEqual(before, {p: file_hash(p) for p in files})
