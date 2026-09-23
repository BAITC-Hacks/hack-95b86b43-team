from decimal import Decimal

import pytest

from backend.app.modules.imports.csv_loader import load_csv_dataset, validate_directory
from tests.helpers import change, read_table, write_table


def test_valid_dataset(dataset_dir, context):
    result = load_csv_dataset(dataset_dir, context)
    assert result.report.valid
    assert result.report.errors == []
    assert len(result.dataset.products) == 3
    assert len({sale.customer_anon_id for sale in result.dataset.sales}) == 10
    assert (context.history_end - context.history_start).days + 1 == 30


def test_leading_zeros_and_decimal(dataset_dir, context):
    result = load_csv_dataset(dataset_dir, context)
    assert result.dataset.products[0].sku == "00123"
    assert result.dataset.sales[0].sku == "00123"
    assert result.dataset.sales[0].qty == Decimal("12.75")
    assert isinstance(result.dataset.sales[0].qty, Decimal)


def test_utf8_bom(dataset_dir, context):
    fields, rows = read_table(dataset_dir, "products")
    write_table(dataset_dir, "products", fields, rows, encoding="utf-8-sig")
    assert validate_directory(dataset_dir, context).valid


def test_diagnostic_location_and_no_partial_dataset(dataset_dir, context):
    change(dataset_dir, "sales", "date", "not-a-date")
    result = load_csv_dataset(dataset_dir, context)
    assert result.dataset is None
    error = next(e for e in result.report.errors if e.code == "INVALID_VALUE")
    assert (error.file, error.row, error.field) == ("sales.csv", 2, "date")
    assert result.report.row_counts["sales.csv"] == result.report.accepted_row_counts["sales.csv"] + 1


@pytest.mark.parametrize("table", ["sales", "stockouts", "inbound"])
def test_empty_optional_tables(dataset_dir, context, table):
    fields, _ = read_table(dataset_dir, table)
    write_table(dataset_dir, table, fields, [])
    assert validate_directory(dataset_dir, context).valid


def test_missing_file(dataset_dir, context):
    (dataset_dir / "stockouts.csv").unlink()
    report = validate_directory(dataset_dir, context)
    assert not report.valid
    assert any(e.code == "MISSING_FILE" and e.file == "stockouts.csv" for e in report.errors)


def test_missing_column(dataset_dir, context):
    fields, rows = read_table(dataset_dir, "sales")
    fields.remove("customer_anon_id")
    for row in rows:
        row.pop("customer_anon_id")
    write_table(dataset_dir, "sales", fields, rows)
    report = validate_directory(dataset_dir, context)
    assert any(e.code == "MISSING_COLUMN" and e.field == "customer_anon_id" for e in report.errors)


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "1,25", "1e3", "-1"])
def test_invalid_quantity(dataset_dir, context, value):
    change(dataset_dir, "sales", "qty", value)
    assert not validate_directory(dataset_dir, context).valid


@pytest.mark.parametrize("value", ["20260802", "02.08.2026", "2026-02-30", "2026-08-02T00:00:00"])
def test_invalid_date(dataset_dir, context, value):
    change(dataset_dir, "sales", "date", value)
    assert not validate_directory(dataset_dir, context).valid


def test_warning_is_not_error_and_repeatable(dataset_dir, context):
    first = validate_directory(dataset_dir, context)
    second = validate_directory(dataset_dir, context)
    assert first.valid and first.warnings
    assert any(w.code == "SHORT_HISTORY" for w in first.warnings)
    assert first.model_dump_json() == second.model_dump_json()


def test_malformed_csv(dataset_dir, context):
    path = dataset_dir / "sales.csv"
    with path.open("a", encoding="utf-8") as stream:
        stream.write('"unfinished')
    report = validate_directory(dataset_dir, context)
    assert not report.valid
    assert any(e.code == "INVALID_CSV" for e in report.errors)


def test_wrong_encoding(dataset_dir, context):
    (dataset_dir / "products.csv").write_bytes(b"\xff\xfe\xff")
    assert any(e.code == "INVALID_ENCODING" for e in validate_directory(dataset_dir, context).errors)


def test_optional_empty_field(dataset_dir, context):
    fields, rows = read_table(dataset_dir, "sales")
    fields.append("order_id")
    for row in rows:
        row["order_id"] = ""
    write_table(dataset_dir, "sales", fields, rows)
    result = load_csv_dataset(dataset_dir, context)
    assert result.report.valid
    assert result.dataset.sales[0].order_id is None
