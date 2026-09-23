import pytest

from backend.app.modules.imports.csv_loader import validate_directory
from tests.helpers import change, read_table, write_table


@pytest.mark.parametrize("table,field,value,code", [
    ("sales", "sku", "UNKNOWN", "UNKNOWN_SKU"),
    ("sales", "warehouse_id", "UNKNOWN", "UNKNOWN_WAREHOUSE"),
    ("products", "category_id", "UNKNOWN", "UNKNOWN_CATEGORY"),
    ("inbound", "supplier_id", "UNKNOWN", "UNKNOWN_SUPPLIER"),
    ("inventory", "on_hand", "1", "INVALID_AVAILABLE_STOCK"),
    ("inventory", "on_hand", "-1", "INVALID_VALUE"),
    ("inventory", "reserved", "-1", "INVALID_VALUE"),
    ("inventory", "blocked", "-1", "INVALID_VALUE"),
    ("inventory", "snapshot_date", "2026-08-31", "WRONG_SNAPSHOT_DATE"),
    ("sales", "date", "2026-09-01", "SALE_OUTSIDE_HISTORY"),
    ("inbound", "qty_received", "1000", "RECEIVED_EXCEEDS_ORDERED"),
    ("inbound", "qty_ordered", "-1", "INVALID_VALUE"),
    ("inbound", "qty_received", "-1", "INVALID_VALUE"),
    ("inbound", "status", "received", "INCONSISTENT_RECEIVED_STATUS"),
    ("stockouts", "end_date_exclusive", "2026-08-09", "INVALID_STOCKOUT_INTERVAL"),
    ("product_suppliers", "is_primary", "false", "MISSING_PRIMARY_SUPPLIER"),
])
def test_business_errors(dataset_dir, context, table, field, value, code):
    change(dataset_dir, table, field, value)
    report = validate_directory(dataset_dir, context)
    assert not report.valid
    assert any(e.code == code for e in report.errors), report.model_dump_json()


@pytest.mark.parametrize("table", ["sales", "inbound", "inventory", "products", "product_suppliers"])
def test_duplicates(dataset_dir, context, table):
    fields, rows = read_table(dataset_dir, table)
    rows.append(dict(rows[0]))
    write_table(dataset_dir, table, fields, rows)
    report = validate_directory(dataset_dir, context)
    assert not report.valid
    assert any(e.code == "DUPLICATE_KEY" for e in report.errors)


def test_multiple_primary_suppliers(dataset_dir, context):
    fields, rows = read_table(dataset_dir, "product_suppliers")
    rows.append({**rows[0], "supplier_id": "SUP-2"})
    write_table(dataset_dir, "product_suppliers", fields, rows)
    assert any(e.code == "MULTIPLE_PRIMARY_SUPPLIERS" for e in validate_directory(dataset_dir, context).errors)


@pytest.mark.parametrize("start,end,overlaps", [
    ("2026-08-11", "2026-08-14", True),
    ("2026-08-10", "2026-08-11", True),
    ("2026-08-12", "2026-08-13", False),
])
def test_interval_boundaries(dataset_dir, context, start, end, overlaps):
    fields, rows = read_table(dataset_dir, "stockouts")
    rows.append({**rows[0], "start_date": start, "end_date_exclusive": end})
    write_table(dataset_dir, "stockouts", fields, rows)
    errors = validate_directory(dataset_dir, context).errors
    assert any(e.code == "OVERLAPPING_STOCKOUT" for e in errors) == overlaps


@pytest.mark.parametrize("day,operation,conflict", [
    ("2026-08-10", "sale", True),
    ("2026-08-11", "sale", True),
    ("2026-08-12", "sale", False),
    ("2026-08-10", "return", False),
])
def test_sales_during_stockout(dataset_dir, context, day, operation, conflict):
    change(dataset_dir, "sales", "date", day)
    change(dataset_dir, "sales", "operation_type", operation)
    errors = validate_directory(dataset_dir, context).errors
    assert any(e.code == "SALE_DURING_STOCKOUT" for e in errors) == conflict


@pytest.mark.parametrize("status,expected", [("in_transit", True), ("confirmed", True), ("cancelled", False)])
def test_overdue_warning(dataset_dir, context, status, expected):
    change(dataset_dir, "inbound", "eta", "2026-08-31")
    change(dataset_dir, "inbound", "status", status)
    report = validate_directory(dataset_dir, context)
    assert report.valid
    assert any(w.code == "OVERDUE_INBOUND" for w in report.warnings) == expected
