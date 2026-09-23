import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.engine.preprocessing.report import generate_preprocessing_report
from backend.app.engine.preprocessing.sales_cleaning import prepare_sales
from backend.app.modules.imports.csv_loader import load_csv_dataset
from backend.synthetic.generator import GenerationConfig, generate_dataset


@pytest.fixture(scope="module")
def synthetic_prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("preparation") / "synthetic"
    generate_dataset(root)
    result = load_csv_dataset(root, GenerationConfig().context)
    assert result.report.valid
    # Block hidden ground-truth reads for the entire production preparation call.
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path.name == "metadata.json" or "metadata" in path.parts:
            raise AssertionError("Preprocessing read synthetic truth")
        return original_open(path, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", guarded)
        prepared = prepare_sales(result.dataset)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    return root, result.dataset, metadata, prepared


def test_synthetic_all_one_off_parts_found(synthetic_prepared):
    _, source, meta, prepared = synthetic_prepared
    rows = {r.original.sale_line_id: r for r in prepared.normalized_sales}
    for event in meta["large_events"]:
        if event["kind"] != "recurring":
            assert all(rows[line].is_excluded_from_baseline for line in event["sale_line_ids"])
            assert len({rows[line].event_id for line in event["sale_line_ids"]}) == 1
    assert len(prepared.normalized_sales) == len(source.sales)
    assert {r.original.sale_line_id for r in prepared.normalized_sales} == {r.sale_line_id for r in source.sales}


def test_synthetic_all_recurring_orders_retained(synthetic_prepared):
    _, _, meta, prepared = synthetic_prepared
    rows = {r.original.sale_line_id: r for r in prepared.normalized_sales}
    recurring = [e for e in meta["large_events"] if e["kind"] == "recurring"]
    assert len(recurring) == 24
    assert all(not rows[line].is_excluded_from_baseline for e in recurring for line in e["sale_line_ids"])


def test_synthetic_censored_days_estimated(synthetic_prepared):
    _, source, _, prepared = synthetic_prepared
    unavailable = [d for d in prepared.daily if not d.availability]
    assert len(unavailable) == sum((s.end_date_exclusive - s.start_date).days for s in source.stockouts)
    assert all(d.observed_sales == 0 and d.estimated_demand >= 0 for d in unavailable)
    assert any(d.estimated_demand > 0 for d in unavailable)
    assert all(d.latest_donor_date is None or d.latest_donor_date < d.date for d in unavailable)


def test_synthetic_report_and_precision_accounting(synthetic_prepared):
    _, _, meta, prepared = synthetic_prepared
    report = generate_preprocessing_report(prepared)
    assert report["sku_count"] == 120 and report["warehouse_count"] == 2
    assert report["processed_rows"] == report["input_rows"]
    assert report["excluded_events"] >= 3
    assert report["stockout_sales_conflicts"] == 0
    assert report["top_10_large_events"]
    # Count false exclusions against truth; do not claim every statistical alert is a true project.
    true_lines = {line for e in meta["large_events"] if e["kind"] != "recurring" for line in e["sale_line_ids"]}
    false_excluded = [r for r in prepared.normalized_sales if r.is_excluded_from_baseline and r.original.sale_line_id not in true_lines]
    assert len(false_excluded) / len(prepared.normalized_sales) < .001


def test_synthetic_historical_cutoff_is_prefix_invariant(synthetic_prepared):
    _, source, _, prepared = synthetic_prepared
    # Include project + split dates but no later months, on a small SKU subset.
    selected = {"00001", "00002", "00003", "00004"}
    subset = source.model_copy(update={
        "products": [p for p in source.products if p.sku in selected],
        "inventory": [r for r in source.inventory if r.sku in selected],
        "sales": [r for r in source.sales if r.sku in selected],
        "stockouts": [r for r in source.stockouts if r.sku in selected],
    })
    cutoff = date(2026, 4, 22)
    prefix = prepare_sales(subset, cutoff)
    assert prefix.events == [e for e in prepared.events if e.sku in selected and e.date <= cutoff]
    # These SKUs have ample own history, so category fallback isn't needed.
    assert prefix.daily == [d for d in prepared.daily if d.sku in selected and d.date <= cutoff]


def test_synthetic_example_conserves_real_sales(synthetic_prepared):
    _, _, meta, prepared = synthetic_prepared
    project = next(e for e in meta["large_events"] if e["kind"] == "one_off" and e["sku"] == "00001")
    day = next(d for d in prepared.daily if d.sku == "00001" and d.warehouse_id == "WH-01"
               and d.date.isoformat() == project["parts"][0]["date"])
    assert day.excluded_sales_qty == Decimal("800")
    assert day.gross_sales_qty - day.excluded_sales_qty == day.demand_for_baseline
