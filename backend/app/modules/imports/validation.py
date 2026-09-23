"""Structural checks; do not invent semantics for partner exports."""
from datetime import date
from decimal import Decimal
import re


def normalize_observations(row, context):
    values, diagnostics = [], []
    if row.errors:
        return [], [("error", "invalid_source_value", error) for error in row.errors]
    if row.kind in {"non_product", "seasonality"}:
        return [], []
    if not row.code:
        return [], [("error", "missing_product_code", "Product code is missing")]
    fields = row.fields
    unit = fields.get("ед.", fields.get("ед.изм"))
    warehouse = fields.get("склад")  # Unknown is not silently changed to a total warehouse.

    def add(field, quantity, semantics, period=None, occurred_at=None):
        if quantity is not None and (not isinstance(quantity, Decimal) or not quantity.is_finite()):
            diagnostics.append(("error", "invalid_quantity", f"Invalid quantity in {field}"))
            return
        values.append(dict(field=field, quantity=quantity, semantics=semantics, period=period,
                           occurred_at=occurred_at, unit=unit, warehouse=warehouse))

    for key, value in fields.items():
        if re.fullmatch(r"\d{4}-\d{2}-01", key):
            add(key, value, row.kind, date.fromisoformat(key))
    if row.kind == "transactions":
        quantity = fields.get("количество")
        add("количество", quantity, "signed_movement_unconfirmed", occurred_at=fields.get("дата"))
        if quantity is None:
            diagnostics.append(("error", "missing_quantity", "Transaction quantity is unknown"))
        if not fields.get("дата") or not fields.get("номер") or not unit or not warehouse:
            diagnostics.append(("error", "incomplete_transaction", "Date, document, unit and warehouse are required"))
    if row.kind == "constraints":
        for key in ("кратность", "мин. разр. к отгр."):
            if key in fields:
                value = fields[key]
                add(key, value, "order_multiple" if key == "кратность" else "minimum_order")
                if value is None or value <= 0:
                    diagnostics.append(("error", "invalid_constraint", "Constraint must be positive and known"))
    if row.kind == "summary":
        snapshot = date.fromisoformat(context["snapshot_date"]) if context.get("snapshot_date") else None
        for key in ("остаток", "зарезервировано", "свободный остаток"):
            add(key, fields.get(key), "inventory_position_unconfirmed", snapshot)
        stock, reserved, free = (fields.get(k) for k in ("остаток", "зарезервировано", "свободный остаток"))
        if all(v is not None for v in (stock, reserved, free)) and abs(stock - reserved - free) > Decimal("0.000001"):
            diagnostics.append(("error", "stock_mismatch", "Stock minus reserved differs from available stock"))
        for key in ("кэф. роста", "кэф. сез-ти"):
            add(key, fields.get(key), "coefficient_unconfirmed")
    for key, value in fields.items():
        if "поступление до" in key:
            match = re.search(r"поступление до (\d{2})\.(\d{2})\.(\d{4})", key)
            when = date(int(match[3]), int(match[2]), int(match[1])) if match else None
            add(key, value, "inbound_deadline_unconfirmed", when)
        elif key.startswith("сэ в пути"):
            match = re.search(r"(\d{2})\.(\d{2})", key)
            year = context.get("inbound_year")
            when = date(year, int(match[2]), int(match[1])) if match and year else None
            add(key, value, "inbound_expected_unconfirmed", when)
    if any(v["quantity"] is None for v in values):
        diagnostics.append(("warning", "unknown_values", "Blank quantities retained as NULL; no implicit zero filling"))
    if any(v["quantity"] is not None and v["quantity"] < 0 for v in values):
        diagnostics.append(("warning", "negative_values", "Negative values retained without sign inversion or absolute value"))
    if not unit:
        diagnostics.append(("warning", "unknown_unit", "Storage/order unit requires confirmation or a validated catalog join"))
    if any(level == "error" for level, _, _ in diagnostics):
        values = []
    return values, diagnostics
