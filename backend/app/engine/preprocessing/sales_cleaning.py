"""Day-by-day orchestration. No file IO, forecasting, or metadata dependencies."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from backend.app.engine.contracts import InputDataset
from backend.app.engine.outliers import CustomerEventDetector, detect_large_customer_orders
from backend.app.engine.preprocessing.aggregation import aggregate_daily_sales, normalize_sales
from backend.app.engine.preprocessing.models import DailySales, PreparedDay, PreparedSales, PreparationConfig
from backend.app.engine.stockouts import estimate_stockout_demand, recent_observations, stockout_calendar


def build_baseline_demand(daily: DailySales, records, unavailable: bool, history, peer_histories,
                          config: PreparationConfig) -> PreparedDay:
    excluded_sales = sum((r.original.qty for r in records if r.is_excluded_from_baseline
                          and r.original.operation_type == "sale"), Decimal(0))
    excluded_returns = sum((r.original.qty for r in records if r.is_excluded_from_baseline
                           and r.original.operation_type == "return"), Decimal(0))
    cleaned_net = daily.net_sales_qty - excluded_sales + excluded_returns
    common = dict(**daily.model_dump(), availability=0 if unavailable else 1, observed_sales=daily.net_sales_qty,
                  excluded_sales_qty=excluded_sales, excluded_return_qty=excluded_returns,
                  is_large_customer_event=any(r.is_large_customer_event for r in records),
                  is_outlier=any(r.is_outlier for r in records),
                  is_excluded_from_baseline=any(r.is_excluded_from_baseline for r in records))
    reasons = []
    if daily.return_qty:
        reasons.append("return_adjusted")
    if excluded_sales:
        reasons.append("excluded_large_customer_event")
    if excluded_returns:
        reasons.append("linked_return_of_excluded_event")
    if unavailable and daily.gross_sales_qty > 0:
        # Stage 1 blocks this at import. Direct callers still get an explicit quarantine,
        # never gross sales PLUS an imputation or an invented zero baseline.
        return PreparedDay(**common, estimated_demand=None, demand_for_baseline=None,
            demand_status="STOCKOUT_SALES_CONFLICT", estimation_method="conflict_not_estimated",
            reasons=reasons + ["stockout_positive_sales_conflict_manual_review"])
    if unavailable:
        estimate = estimate_stockout_demand(history, daily.date, peer_histories, config)
        estimate["estimated_demand"] = max(Decimal(0), estimate["estimated_demand"] - daily.return_qty + excluded_returns)
        reasons.append("stockout_estimated")
        if estimate["insufficient_history"]:
            reasons.append("insufficient_history_fallback")
        return PreparedDay(**common, **estimate, demand_status="STOCKOUT",
            demand_for_baseline=estimate["estimated_demand"], reasons=reasons)
    if cleaned_net < 0:
        reasons.append("negative_net_returns_preserved")
    return PreparedDay(**common, estimated_demand=max(Decimal(0), daily.net_sales_qty), demand_for_baseline=cleaned_net,
        demand_status="AVAILABLE", estimation_method="observed",
        insufficient_history=len(recent_observations(history, daily.date, config)) < config.min_recent_days,
        reasons=reasons + ["available_day_after_exclusion" if excluded_sales or excluded_returns else "normal_available_day"])


def prepare_sales(dataset: InputDataset, cutoff_date: date | None = None,
                  config: PreparationConfig | None = None) -> PreparedSales:
    config = config or PreparationConfig()
    cutoff = cutoff_date or dataset.context.history_end
    if not dataset.context.history_start <= cutoff <= dataset.context.history_end:
        raise ValueError("cutoff_date must be within the declared history")
    normalized = normalize_sales(dataset.sales, cutoff)
    aggregates = aggregate_daily_sales(normalized)
    products = {p.sku: p for p in dataset.products}
    inventory = {(r.sku, r.warehouse_id): r for r in dataset.inventory}
    starts = {}
    for pair, record in inventory.items():
        starts[pair] = max(dataset.context.history_start, products[pair[0]].active_from,
                           record.availability_start or dataset.context.history_start)
    for row in normalized:
        sale = row.original
        pair = sale.sku, sale.warehouse_id
        if sale.date < dataset.context.history_start or sale.date < products[sale.sku].active_from:
            raise ValueError("Sale outside active history")
        if pair not in starts:
            # Historical pair absent from current inventory: no evidence of earlier assortment.
            starts[pair] = sale.date
        if sale.date < starts[pair]:
            raise ValueError("Sale predates warehouse availability_start")
    pairs = sorted(pair for pair in starts if starts[pair] <= cutoff)
    peer_pairs = defaultdict(list)
    for sku, warehouse in pairs:
        product = products[sku]
        peer_pairs[product.category_id, product.base_unit, warehouse].append((sku, warehouse))
    unavailable = stockout_calendar(dataset.stockouts, dataset.context.history_start, cutoff)
    by_day = defaultdict(list)
    for row in normalized:
        by_day[row.original.date].append(row)
    histories = defaultdict(list)
    detector = CustomerEventDetector(config)
    days, events = [], []
    day = dataset.context.history_start
    while day <= cutoff:
        records = by_day[day]
        events.extend(detect_large_customer_orders(records, day, histories, detector))
        by_pair = defaultdict(list)
        for record in records:
            sale = record.original
            if record.is_technical_duplicate:
                continue
            if sale.operation_type == "return" and sale.order_id:
                key = sale.sku, sale.warehouse_id, sale.customer_anon_id, sale.order_id
                if key in detector.excluded_orders:
                    record.is_excluded_from_baseline = True
                    record.reasons.append("linked_return_of_excluded_event")
            by_pair[sale.sku, sale.warehouse_id].append(record)
        pending_history = []
        for sku, warehouse in pairs:
            pair = sku, warehouse
            if day < starts[pair]:
                continue
            daily = aggregates.get((day, sku, warehouse)) or DailySales(date=day, sku=sku, warehouse_id=warehouse)
            product = products[sku]
            peers = [histories[p] for p in peer_pairs[product.category_id, product.base_unit, warehouse] if p != pair]
            prepared = build_baseline_demand(daily, by_pair[pair], (day, sku, warehouse) in unavailable,
                                              histories[pair], peers, config)
            days.append(prepared)
            if prepared.availability and not prepared.is_excluded_from_baseline:
                # Retain negative net in output; historical donor rates cannot be negative.
                pending_history.append((pair, (day, max(Decimal(0), prepared.demand_for_baseline))))
        # Updates happen after ALL SKUs: no same-day peer leakage or SKU-order dependence.
        for pair, observation in pending_history:
            histories[pair].append(observation)
            histories[pair] = [(d, q) for d, q in histories[pair] if (day - d).days < config.max_history_age_days]
        day += timedelta(days=1)
    return PreparedSales(cutoff_date=cutoff, config=config, input_rows=len(dataset.sales),
        ignored_future_rows=sum(s.date > cutoff for s in dataset.sales),
        normalized_sales=normalized, daily=days, events=events)
