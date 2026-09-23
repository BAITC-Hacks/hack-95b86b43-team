from collections import Counter, defaultdict
from decimal import Decimal

from backend.app.engine.preprocessing.models import PreparedSales


def generate_preprocessing_report(prepared: PreparedSales) -> dict:
    large, excluded = {}, {}
    for event in prepared.events:
        if event.is_large_customer_event:
            large[event.event_id] = event
        if event.is_excluded_from_baseline:
            excluded[event.event_id] = event
    totals = defaultdict(Decimal)
    latest = {}
    for day in prepared.daily:
        totals[day.sku] += max(Decimal(0), day.demand_for_baseline or Decimal(0))
        latest[day.sku, day.warehouse_id] = day
    top = sorted(large.values(), key=lambda e: (-e.large_event_score, e.date, e.event_id))[:10]
    return {
        "algorithm_version": prepared.algorithm_version,
        "cutoff_date": prepared.cutoff_date.isoformat(), "config": prepared.config.model_dump(mode="json"),
        "input_rows": prepared.input_rows, "processed_rows": len(prepared.normalized_sales),
        "ignored_future_rows": prepared.ignored_future_rows,
        "technical_duplicates": sum(r.is_technical_duplicate for r in prepared.normalized_sales),
        "daily_records": len(prepared.daily), "sku_count": len(totals),
        "warehouse_count": len({d.warehouse_id for d in prepared.daily}),
        "stockout_days": sum(d.availability == 0 for d in prepared.daily),
        "estimated_stockout_days": sum(d.demand_status == "STOCKOUT" for d in prepared.daily),
        "positive_estimated_stockout_days": sum(d.demand_status == "STOCKOUT" and d.estimated_demand > 0 for d in prepared.daily),
        "stockout_sales_conflicts": sum(d.demand_status == "STOCKOUT_SALES_CONFLICT" for d in prepared.daily),
        "large_customer_events": len(large), "excluded_events": len(excluded),
        "returns_count": sum(r.original.operation_type == "return" and not r.is_technical_duplicate for r in prepared.normalized_sales),
        "insufficient_history_sku_count": len({d.sku for d in prepared.daily if d.insufficient_history}),
        "insufficient_history_sku_at_cutoff": len({d.sku for d in latest.values() if d.insufficient_history}),
        "zero_demand_sku_count": sum(q == 0 for q in totals.values()),
        "estimation_methods": dict(sorted(Counter(d.estimation_method for d in prepared.daily if not d.availability).items())),
        "top_10_large_events": [{
            "event_id": e.event_id, "sku": e.sku, "warehouse": e.warehouse_id, "customer": e.customer_anon_id,
            "date": e.date.isoformat(), "start_date": e.start_date.isoformat(), "actual_qty": str(e.actual_qty),
            "typical_qty": str(e.typical_qty), "score": str(e.large_event_score),
            "excluded": e.is_excluded_from_baseline, "reason": e.large_event_reason} for e in top],
    }
