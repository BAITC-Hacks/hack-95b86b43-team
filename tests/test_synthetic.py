import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.modules.imports.csv_loader import TABLE_MODELS, load_csv_dataset
from backend.app.modules.imports.schemas import ValidationIssue, ValidationReport
from backend.synthetic import generator
from backend.synthetic.demand import SCENARIO_COUNTS
from backend.synthetic.generator import GenerationConfig, generate_dataset


def rows(directory, name):
    with (directory / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def hashes(directory):
    result = {}
    for file in sorted(directory.rglob("*")):
        if file.is_file():
            with file.open("rb") as stream:
                result[file.relative_to(directory).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    directory = tmp_path_factory.mktemp("synthetic") / "dataset"
    summary = generate_dataset(directory)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    return directory, summary, metadata


def test_same_seed_is_byte_identical(generated, tmp_path):
    directory, _, _ = generated
    second = tmp_path / "same"
    generate_dataset(second, GenerationConfig(seed=42))
    assert hashes(directory) == hashes(second)


def test_different_seed_changes_observations(generated, tmp_path):
    other = tmp_path / "different"
    generate_dataset(other, GenerationConfig(seed=43))
    assert hashes(generated[0])["sales.csv"] != hashes(other)["sales.csv"]


def test_scale_and_valid_contract(generated):
    directory, summary, _ = generated
    assert summary["sku_count"] == 120
    assert 30_000 < summary["sales_rows"] < 100_000
    assert summary["customer_count"] == 300
    assert summary["scenario_counts"] == SCENARIO_COUNTS
    assert summary["history_start"] == "2024-09-01"
    assert summary["history_end"] == "2026-08-31"
    assert summary["as_of_date"] == "2026-09-01"
    for name in TABLE_MODELS:
        assert (directory / f"{name}.csv").exists()
    assert len(rows(directory, "categories.csv")) == 6
    assert len(rows(directory, "warehouses.csv")) == 2
    assert len(rows(directory, "suppliers.csv")) == 8
    result = load_csv_dataset(directory, GenerationConfig().context)
    assert result.report.valid
    assert result.report.errors == []
    assert {w.code for w in result.report.warnings} == {"OVERDUE_INBOUND"}


def test_customer_events_are_observed_and_separate(generated):
    directory, _, metadata = generated
    sales = {row["sale_line_id"]: row for row in rows(directory, "sales.csv")}
    one_off = [e for e in metadata["large_events"] if e["kind"].startswith("one_off")]
    recurring = [e for e in metadata["large_events"] if e["kind"] == "recurring"]
    assert len(one_off) == 3
    assert len(recurring) == 24
    for event in one_off + recurring:
        observed = [sales[line] for line in event["sale_line_ids"]]
        assert sum(Decimal(r["qty"]) for r in observed) == sum(Decimal(p["qty"]) for p in event["parts"])
        assert {r["customer_anon_id"] for r in observed} == {event["customer_anon_id"]}
        assert {r["order_id"] for r in observed} == {event["order_id"]}
    assert all(Decimal("500") <= sum(Decimal(p["qty"]) for p in e["parts"]) <= Decimal("1000") for e in one_off)
    split = next(e for e in one_off if e["kind"] == "one_off_split")
    assert len(split["sale_line_ids"]) == 6
    assert len({p["date"] for p in split["parts"]}) == 3
    assert len({e["customer_anon_id"] for e in recurring}) == 1
    assert len({e["parts"][0]["date"][:7] for e in recurring}) == 24
    assert {e["sku"] for e in recurring}.isdisjoint({e["sku"] for e in one_off})


def test_inbound_and_snapshot_classes(generated):
    directory, _, metadata = generated
    inbound = rows(directory, "inbound.csv")
    as_of = date.fromisoformat(metadata["as_of_date"])
    horizon = as_of + timedelta(days=metadata["demo_horizon_days"])
    assert any(r["status"] == "received" and date.fromisoformat(r["eta"]) < as_of for r in inbound)
    assert any(r["status"] == "in_transit" and as_of <= date.fromisoformat(r["eta"]) <= horizon for r in inbound)
    assert any(r["status"] != "received" and date.fromisoformat(r["eta"]) > horizon for r in inbound)
    assert any(r["status"] == "confirmed" and date.fromisoformat(r["eta"]) < as_of for r in inbound)
    assert any(0 < Decimal(r["qty_received"]) < Decimal(r["qty_ordered"]) for r in inbound)
    assert {r["stock_class"] for r in metadata["inventory_scenarios"]} == {"high", "normal", "low", "zero"}
    assert any(Decimal(r["on_hand"]) == 0 for r in rows(directory, "inventory.csv"))


def test_leading_zeros_fractions_and_primary_suppliers(generated):
    directory, _, _ = generated
    assert rows(directory, "products.csv")[0]["sku"] == "00001"
    assert any(Decimal(r["qty"]) % 1 != 0 for r in rows(directory, "sales.csv"))
    assert Counter(r["sku"] for r in rows(directory, "product_suppliers.csv") if r["is_primary"] == "true") == {
        r["sku"]: 1 for r in rows(directory, "products.csv")}


def test_hidden_truth_is_not_a_model_input(generated, monkeypatch):
    directory, _, _ = generated
    original_open = Path.open

    def no_metadata_reads(path, *args, **kwargs):
        assert "metadata" not in path.parts and path.name != "metadata.json"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_metadata_reads)
    result = load_csv_dataset(directory, GenerationConfig().context)
    assert result.report.valid
    for table in TABLE_MODELS:
        fields = TABLE_MODELS[table].model_fields
        assert "scenario_type" not in fields
        assert "true_demand" not in fields
    assert "metadata" not in type(result.dataset).model_fields


def test_stock_ledger_and_lost_demand(generated):
    directory, _, metadata = generated
    observed = defaultdict(Decimal)
    for sale in rows(directory, "sales.csv"):
        observed[(sale["sku"], sale["warehouse_id"], sale["date"])] += Decimal(sale["qty"])
        assert sale["order_id"].startswith("ORDER-")
        assert sale["customer_anon_id"].startswith("CUST-")
    balances = defaultdict(Decimal)
    receipts = defaultdict(Decimal)
    lost = Decimal(0)
    with (directory / "metadata/true_demand.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            pair = row["sku"], row["warehouse_id"]
            key = (*pair, row["date"])
            opening, received, closing = (Decimal(row[f]) for f in ("opening_stock", "receipts", "closing_stock"))
            true, sold, missing = (Decimal(row[f]) for f in ("true_demand", "observed_sales", "lost_total_demand"))
            assert opening == balances[pair]
            assert opening + received - sold == closing >= 0
            assert sold == observed[key]
            assert true == sold + missing
            assert true == sum(Decimal(row[f]) for f in ("regular_demand", "recurring_client_demand", "one_off_demand"))
            assert sold <= opening + received
            receipts[pair] += received
            balances[pair] = closing
            lost += missing
    assert lost > 0
    actual_received = defaultdict(Decimal)
    for row in rows(directory, "inbound.csv"):
        actual_received[row["sku"], row["warehouse_id"]] += Decimal(row["qty_received"])
    assert receipts == actual_received
    for row in rows(directory, "inventory.csv"):
        assert Decimal(row["on_hand"]) == balances[row["sku"], row["warehouse_id"]]
        assert Decimal(row["reserved"]) + Decimal(row["blocked"]) <= Decimal(row["on_hand"])
    intervals = rows(directory, "stockouts.csv")
    assert intervals
    for planned in metadata["stockout_intervals"]:
        assert any(r["sku"] == planned["sku"] and r["warehouse_id"] == planned["warehouse_id"]
                   and r["start_date"] <= planned["start_date"]
                   and r["end_date_exclusive"] >= planned["end_date_exclusive"] for r in intervals)
    lengths = [(date.fromisoformat(r["end_date_exclusive"]) - date.fromisoformat(r["start_date"])).days
               for r in metadata["stockout_intervals"]]
    assert any(5 <= length <= 10 for length in lengths)
    assert any(10 <= length <= 20 for length in lengths)


def test_scenario_behavior(generated):
    directory, _, metadata = generated
    specs = {s["sku"]: s for s in metadata["skus"]}
    sparse_days = sparse_zeros = 0
    growth_means, decline_means = defaultdict(list), defaultdict(list)
    with (directory / "metadata/true_demand.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            spec = specs[row["sku"]]
            assert row["date"] >= spec["active_from"]
            if spec["scenario_type"] == "intermittent":
                sparse_days += 1
                sparse_zeros += Decimal(row["regular_demand"]) == 0
            if row["warehouse_id"] == "WH-01":
                if spec["scenario_type"] == "growth":
                    growth_means[row["sku"]].append(Decimal(row["expected_regular_qty"]))
                elif spec["scenario_type"] == "declining":
                    decline_means[row["sku"]].append(Decimal(row["expected_regular_qty"]))
    assert sparse_zeros / sparse_days > .9
    assert all(values[-1] > values[0] * Decimal("1.5") for values in growth_means.values())
    assert all(values[-1] < values[0] * Decimal(".7") for values in decline_means.values())
    assert all(s["active_from"] > metadata["history_start"] for s in specs.values() if s["scenario_type"] == "new")
    assert {s["seasonal_profile"] for s in specs.values()} == {"flat", "summer", "winter", "spring_autumn"}


def test_generation_refuses_foreign_directory(tmp_path):
    (tmp_path / "sales.csv").write_text("real data must stay intact", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        generate_dataset(tmp_path)
    assert (tmp_path / "sales.csv").read_text(encoding="utf-8") == "real data must stay intact"


def test_failed_validation_is_not_success(tmp_path, monkeypatch):
    def reject(*args):
        return ValidationReport(errors=[ValidationIssue(code="TEST", file="sales.csv", message="Injected failure")])
    monkeypatch.setattr(generator, "validate_directory", reject)
    config = GenerationConfig(start_date=date(2026, 3, 1), end_date=date(2026, 8, 31))
    with pytest.raises(ValueError, match="failed validation"):
        generate_dataset(tmp_path / "invalid", config)
    metadata = json.loads((tmp_path / "invalid/metadata.json").read_text(encoding="utf-8"))
    assert metadata["validation_valid"] is False


def test_cli_custom_dates_and_regeneration(tmp_path):
    command = [sys.executable, "-m", "backend.generate_synthetic", "--output", str(tmp_path / "cli"),
               "--seed", "9", "--start-date", "2026-03-01", "--end-date", "2026-08-31"]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["valid"] and report["history_start"] == "2026-03-01"
    initial = hashes(tmp_path / "cli")
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode == 0, repeated.stderr
    assert initial == hashes(tmp_path / "cli")


@pytest.mark.parametrize("start,end", [("bad", "2026-08-31"), ("2026-09-01", "2026-08-31"),
                                      ("2026-08-01", "2026-08-31")])
def test_cli_rejects_invalid_period(tmp_path, start, end):
    result = subprocess.run([sys.executable, "-m", "backend.generate_synthetic", "--output", str(tmp_path / "bad"),
                             "--start-date", start, "--end-date", end], capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stderr)["valid"] is False
    assert not (tmp_path / "bad").exists()
