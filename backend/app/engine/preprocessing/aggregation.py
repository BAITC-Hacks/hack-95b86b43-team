from collections import defaultdict
from datetime import date
from decimal import Decimal

from backend.app.engine.contracts import Sale
from backend.app.engine.preprocessing.models import DailySales, NormalizedSale


def normalize_sales(sales: list[Sale], cutoff: date) -> list[NormalizedSale]:
    """Dates/Decimals were validated at import; keep every source row intact."""
    seen = {}
    result = []
    for sale in sorted((s for s in sales if s.date <= cutoff),
                       key=lambda s: (s.date, s.sku, s.warehouse_id, s.sale_line_id, s.source_file, s.source_row)):
        identity = sale.model_dump(exclude={"source_file", "source_row"})
        duplicate = sale.sale_line_id in seen
        if duplicate and seen[sale.sale_line_id] != identity:
            raise ValueError(f"Conflicting duplicate sale_line_id: {sale.sale_line_id}")
        seen[sale.sale_line_id] = identity
        result.append(NormalizedSale(original=sale, signed_qty=sale.qty if sale.operation_type == "sale" else -sale.qty,
            is_technical_duplicate=duplicate, reasons=["technical_duplicate_not_counted"] if duplicate else []))
    return result


def aggregate_daily_sales(sales: list[NormalizedSale]) -> dict[tuple[date, str, str], DailySales]:
    groups = defaultdict(list)
    for row in sales:
        if not row.is_technical_duplicate:
            sale = row.original
            groups[sale.date, sale.sku, sale.warehouse_id].append(row)
    result = {}
    for (day, sku, warehouse), records in sorted(groups.items()):
        gross = sum((r.original.qty for r in records if r.original.operation_type == "sale"), Decimal(0))
        returns = sum((r.original.qty for r in records if r.original.operation_type == "return"), Decimal(0))
        by_customer = defaultdict(Decimal)
        for record in records:
            if record.original.operation_type == "sale":
                by_customer[record.original.customer_anon_id] += record.original.qty
        result[day, sku, warehouse] = DailySales(date=day, sku=sku, warehouse_id=warehouse,
            gross_sales_qty=gross, return_qty=returns, net_sales_qty=gross - returns,
            transaction_count=len(records), unique_customers=len({r.original.customer_anon_id for r in records}),
            max_single_customer_qty=max(by_customer.values(), default=Decimal(0)),
            sale_line_ids=[r.original.sale_line_id for r in records])
    return result
