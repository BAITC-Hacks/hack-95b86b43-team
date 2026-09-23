"""Cross-table validation. Does not repair or discard business facts."""

from collections import defaultdict
from datetime import timedelta

from backend.app.engine.contracts import InputDataset, Record
from backend.app.modules.imports.schemas import ValidationIssue, ValidationReport


def validate_dataset(dataset: InputDataset, report: ValidationReport | None = None) -> ValidationReport:
    if report is None:
        report = ValidationReport(as_of_date=dataset.context.as_of_date)

    def issue(record: Record, code: str, field: str, message: str, warning: bool = False):
        target = report.warnings if warning else report.errors
        target.append(ValidationIssue(
            code=code, file=record.source_file, row=record.source_row,
            field=field, message=message,
        ))

    keys = {
        "products": ("sku",), "categories": ("category_id",),
        "warehouses": ("warehouse_id",), "suppliers": ("supplier_id",),
        "product_suppliers": ("sku", "supplier_id"),
        "sales": ("sale_line_id",), "inventory": ("sku", "warehouse_id"),
        "inbound": ("po_line_id",),
    }
    for table, fields in keys.items():
        seen = set()
        for record in getattr(dataset, table):
            key = tuple(getattr(record, field) for field in fields)
            if key in seen:
                issue(record, "DUPLICATE_KEY", ",".join(fields), "Duplicate record key")
            seen.add(key)

    known = {
        "sku": {r.sku for r in dataset.products},
        "category_id": {r.category_id for r in dataset.categories},
        "warehouse_id": {r.warehouse_id for r in dataset.warehouses},
        "supplier_id": {r.supplier_id for r in dataset.suppliers},
    }
    codes = {
        "sku": "UNKNOWN_SKU", "category_id": "UNKNOWN_CATEGORY",
        "warehouse_id": "UNKNOWN_WAREHOUSE", "supplier_id": "UNKNOWN_SUPPLIER",
    }
    references = {
        "products": ("category_id",),
        "product_suppliers": ("sku", "supplier_id"),
        "sales": ("sku", "warehouse_id"),
        "inventory": ("sku", "warehouse_id"),
        "stockouts": ("sku", "warehouse_id"),
        "inbound": ("sku", "warehouse_id", "supplier_id"),
    }
    for table, fields in references.items():
        for record in getattr(dataset, table):
            for field in fields:
                if getattr(record, field) not in known[field]:
                    issue(record, codes[field], field, "Identifier is absent from its reference table")

    primaries = defaultdict(list)
    for relation in dataset.product_suppliers:
        if relation.is_primary:
            primaries[relation.sku].append(relation)
    for relations in primaries.values():
        for relation in relations[1:]:
            issue(relation, "MULTIPLE_PRIMARY_SUPPLIERS", "is_primary", "SKU has more than one primary supplier")
    checked = set()
    for inventory in dataset.inventory:
        if inventory.sku not in checked and not primaries[inventory.sku]:
            issue(inventory, "MISSING_PRIMARY_SUPPLIER", "sku", "Current assortment SKU needs a primary supplier")
        checked.add(inventory.sku)
        if inventory.reserved + inventory.blocked > inventory.on_hand:
            issue(inventory, "INVALID_AVAILABLE_STOCK", "reserved", "reserved + blocked exceeds on_hand")
        if inventory.snapshot_date != dataset.context.as_of_date:
            issue(inventory, "WRONG_SNAPSHOT_DATE", "snapshot_date", "Snapshot must be at the start of as_of_date")
        if inventory.availability_start and inventory.availability_start > inventory.snapshot_date:
            issue(inventory, "INVALID_AVAILABILITY_START", "availability_start", "Availability starts after snapshot")

    for inbound in dataset.inbound:
        if inbound.qty_received > inbound.qty_ordered:
            issue(inbound, "RECEIVED_EXCEEDS_ORDERED", "qty_received", "Received exceeds ordered quantity")
        if inbound.status == "received" and inbound.qty_received != inbound.qty_ordered:
            issue(inbound, "INCONSISTENT_RECEIVED_STATUS", "status", "Received status requires full receipt")
        if (inbound.status in {"confirmed", "in_transit"}
                and inbound.qty_received < inbound.qty_ordered
                and inbound.eta < dataset.context.as_of_date):
            issue(inbound, "OVERDUE_INBOUND", "eta", "Outstanding inbound has a past ETA", warning=True)

    intervals = defaultdict(list)
    for stockout in dataset.stockouts:
        if stockout.end_date_exclusive <= stockout.start_date:
            issue(stockout, "INVALID_STOCKOUT_INTERVAL", "end_date_exclusive", "End must be after start")
            continue
        intervals[(stockout.sku, stockout.warehouse_id)].append(stockout)
    for records in intervals.values():
        records.sort(key=lambda r: (r.start_date, r.end_date_exclusive, r.source_row))
        latest_end = None
        for record in records:
            if latest_end is not None and record.start_date < latest_end:
                issue(record, "OVERLAPPING_STOCKOUT", "start_date", "Stockout intervals overlap")
            latest_end = max(latest_end or record.end_date_exclusive, record.end_date_exclusive)

    current_pairs = {(r.sku, r.warehouse_id) for r in dataset.inventory}
    products = {r.sku: r for r in dataset.products}
    for sale in dataset.sales:
        if not dataset.context.history_start <= sale.date <= dataset.context.history_end:
            issue(sale, "SALE_OUTSIDE_HISTORY", "date", "Sale is outside the declared complete history")
        if sale.sku in products and sale.date < products[sale.sku].active_from:
            issue(sale, "SALE_BEFORE_ACTIVE", "date", "Sale predates product active_from")
        pair = (sale.sku, sale.warehouse_id)
        if pair not in current_pairs:
            issue(sale, "NO_CURRENT_INVENTORY", "sku", "Historical pair has no current snapshot", warning=True)
        if sale.operation_type == "sale" and sale.qty > 0:
            if any(r.start_date <= sale.date < r.end_date_exclusive for r in intervals[pair]):
                issue(sale, "SALE_DURING_STOCKOUT", "date", "Positive sale within a full-day stockout")

    # Compare calendar anniversaries, including leap years, not an approximate 730 days.
    end_exclusive = dataset.context.history_end + timedelta(days=1)
    try:
        two_years_ago = end_exclusive.replace(year=end_exclusive.year - 2)
    except ValueError:
        two_years_ago = end_exclusive.replace(year=end_exclusive.year - 2, day=28)
    if dataset.context.history_start > two_years_ago:
        report.warnings.append(ValidationIssue(
            code="SHORT_HISTORY", file="sales.csv", field="date",
            message="History is shorter than two calendar years; annual seasonality is limited",
        ))
    report.valid = not report.errors
    return report
