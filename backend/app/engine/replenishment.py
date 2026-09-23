"""Dated replenishment planning with lost sales and auditable stock arithmetic."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from math import ulp

from backend.app.engine.contracts import InputDataset
from backend.app.engine.forecast import fit_forecasts
from backend.app.engine.preprocessing.models import PreparedSales


def _number(value) -> float:
    return round(float(value), 8)


def round_order(quantity: float, moq: Decimal, multiple: Decimal) -> Decimal:
    """MOQ applies only to positive requirements; Decimal preserves pack steps."""
    if multiple <= 0 or moq < 0:
        raise ValueError("Order multiple must be positive and MOQ non-negative")
    if quantity <= 0:
        return Decimal(0)
    # Remove floating-point summation noise, not legitimate fractional demand.
    noise = Decimal(str(min(quantity / 2, max(quantity, float(multiple)) * 1e-12)))
    needed = max(Decimal(str(quantity)) - noise, moq)
    return (needed / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple


def _simulate(available: float, demands: list[float], receipts: list[float],
              lead_days: int, order: float = 0.0) -> tuple[list[float], list[float]]:
    balances, lost = [], []
    stock = available
    for index, demand in enumerate(demands):
        stock += receipts[index] + (order if index == lead_days else 0.0)
        lost.append(max(0.0, demand - stock))
        stock = max(0.0, stock - demand)
        balances.append(stock)
    return balances, lost


def _timed_requirement(available: float, demands: list[float], receipts: list[float],
                       lead: int, safety: float) -> float:
    """Find minimum receipt at lead time to cover later demand and ending safety.

    Pre-arrival lost sales are not backorders. The peak prefix requirement also
    protects a gap before a later existing shipment, even if final balance is high.
    """
    before = available
    for index in range(lead):
        before = max(0.0, before + receipts[index] - demands[index])
    remaining = before
    required = 0.0
    for index in range(lead, len(demands)):
        remaining += receipts[index] - demands[index]
        required = max(required, -remaining)
    requirement = max(0.0, required, safety - remaining)
    # Repeated subtraction of 0.1 can leave 1e-15 and otherwise buy an entire
    # pack. Bound only arithmetic noise, relative to this calculation's scale.
    scale = max(available, sum(demands), sum(receipts), safety)
    tolerance = ulp(scale) * (len(demands) + 2) * 4
    return 0.0 if requirement <= tolerance else requirement


def _events(prepared: PreparedSales, cutoff, use_outliers=True):
    unique = {}
    for event in prepared.events:
        if event.date <= cutoff and (event.is_large_customer_event or event.is_excluded_from_baseline):
            existing = unique.get(event.event_id)
            if existing is None or event.date >= existing.date:
                unique[event.event_id] = event
    grouped = defaultdict(list)
    reasons = {
        "excluded_large_customer_event": "Разовый крупный заказ исключён из регулярного спроса",
        "excluded_large_customer_event_continuation": "Раздробленный разовый заказ: очередные части исключены из регулярного спроса",
        "retained_recurring_large_customer": "Регулярная крупная закупка сохранена в спросе",
        "large_event_insufficient_history_review": "Крупная закупка сохранена: истории недостаточно, нужна проверка",
        "large_event_uncertain_review": "Крупная закупка сохранена: разовый характер не подтверждён, нужна проверка",
        "normal_customer_event": "Обычная закупка сохранена в регулярном спросе",
    }
    for event in sorted(unique.values(), key=lambda e: (e.date, e.event_id)):
        reason = reasons.get(event.large_event_reason, "Нетипичная закупка: требуется проверка")
        if event.is_excluded_from_baseline and not use_outliers:
            reason = "Разовый крупный заказ сохранён в этом сценарии: исключение выбросов отключено"
        grouped[event.sku, event.warehouse_id].append({
            "date": event.start_date.isoformat(), "qty": _number(event.actual_qty),
            "customer": event.customer_anon_id,
            "reason": reason, "reason_code": event.large_event_reason,
            "excluded": event.is_excluded_from_baseline,
        })
    return grouped


def calculate_recommendations(dataset: InputDataset, prepared: PreparedSales, *, warehouse_id=None,
                              category_id=None, review_days=7, safety_days=5,
                              use_stockout=True, use_outliers=True,
                              use_seasonality=True, use_trend=True) -> dict:
    if type(review_days) is not int or not 1 <= review_days <= 90:
        raise ValueError("review_days must be an integer from 1 to 90")
    if type(safety_days) is not int or not 0 <= safety_days <= 90:
        raise ValueError("safety_days must be an integer from 0 to 90")
    forecasts = fit_forecasts(dataset, prepared, use_stockout=use_stockout, use_outliers=use_outliers,
                              use_seasonality=use_seasonality, use_trend=use_trend)
    products = {p.sku: p for p in dataset.products}
    suppliers = {s.supplier_id: s for s in dataset.suppliers}
    primary = defaultdict(list)
    for relation in dataset.product_suppliers:
        if relation.is_primary:
            primary[relation.sku].append(relation)
    inbound = defaultdict(list)
    for shipment in dataset.inbound:
        inbound[shipment.sku, shipment.warehouse_id].append(shipment)
    events = _events(prepared, dataset.context.history_end, use_outliers)
    as_of = dataset.context.as_of_date
    recommendations = []
    for inventory in sorted(dataset.inventory, key=lambda row: (row.warehouse_id, row.sku)):
        product = products[inventory.sku]
        if warehouse_id is not None and inventory.warehouse_id != warehouse_id:
            continue
        if category_id is not None and product.category_id != category_id:
            continue
        if inventory.snapshot_date != as_of:
            raise ValueError("Inventory snapshot must equal as_of_date")
        if len(primary[product.sku]) != 1:
            raise ValueError(f"SKU {product.sku} requires exactly one primary supplier")
        relation = primary[product.sku][0]
        if relation.lead_time_days > 365:
            raise ValueError("Supplier lead time exceeds the supported 365-day planning range")
        supplier = suppliers.get(relation.supplier_id)
        if supplier is None:
            raise ValueError(f"Unknown supplier {relation.supplier_id}")
        pair = product.sku, inventory.warehouse_id
        forecast = forecasts[pair]
        lead = relation.lead_time_days
        horizon = lead + review_days
        dates = [as_of + timedelta(days=offset) for offset in range(horizon)]
        demands = [forecast.demand(day, as_of) for day in dates]
        available = float(inventory.on_hand - inventory.reserved - inventory.blocked)
        if available < 0:
            raise ValueError("Available stock cannot be negative")
        warnings = list(forecast.warnings)
        receipts = [0.0] * horizon
        shipments = []
        overdue = 0
        for shipment in inbound[pair]:
            remaining = shipment.qty_ordered - shipment.qty_received
            if remaining <= 0 or shipment.status not in {"confirmed", "in_transit"}:
                continue
            offset = (shipment.eta - as_of).days
            if offset < 0:
                overdue += 1
                continue
            if offset < horizon:
                receipts[offset] += float(remaining)
                shipments.append({"date": shipment.eta.isoformat(), "qty": _number(remaining),
                                  "id": shipment.po_line_id})
        if overdue:
            warnings.append(f"Просроченных поставок: {overdue}. Количество исключено до подтверждения нового ETA.")
        forecast_total = sum(demands)
        safety = forecast_total / horizon * safety_days
        balance_need = max(0.0, forecast_total + safety - available - sum(receipts))
        raw = _timed_requirement(available, demands, receipts, lead, safety)
        moq = relation.moq or Decimal(0)
        default_multiple = Decimal(1) if product.base_unit.lower() in {"pcs", "шт", "шт.", "piece", "pieces"} else Decimal("0.01")
        multiple = relation.order_multiple or default_multiple
        recommended = round_order(raw, moq, multiple)
        without, lost_without = _simulate(available, demands, receipts, lead)
        with_order, lost_with = _simulate(available, demands, receipts, lead, float(recommended))
        first_shortage = next((index for index, qty in enumerate(lost_without) if qty > 1e-8), None)
        before_arrival = sum(lost_without[:lead])
        if before_arrival > 1e-8:
            urgency = "critical"
            warnings.append("Дефицит ожидается до новой поставки: обычный заказ его не устранит. Проверьте ускорение или перемещение.")
        elif forecast.needs_review:
            urgency = "review"
        elif recommended > 0 and first_shortage is not None:
            urgency = "order_now"
        elif recommended > 0:
            urgency = "reserve"
        else:
            urgency = "none"
        if any(day.return_qty > 0 for day, _ in forecast.historical):
            warnings.append("Возвраты учтены в чистом спросе; отрицательный средний спрос ограничен нулём.")
        stockout_days = sum(not day.availability for day, _ in forecast.historical)
        estimated_lost = sum(max(0.0, float(day.estimated_demand or 0) - float(day.observed_sales))
                             for day, _ in forecast.historical if not day.availability)
        excluded_qty = sum(float(day.excluded_sales_qty - day.excluded_return_qty)
                           for day, _ in forecast.historical)
        product_events = events[pair]
        months = defaultdict(lambda: [0.0, 0.0])
        for day, selected in forecast.historical:
            key = day.date.replace(day=1).isoformat()
            months[key][0] += float(day.observed_sales)
            months[key][1] += selected if selected is not None else 0.0
        chart = [{"date": day, "observed": _number(values[0]), "baseline": _number(max(0.0, values[1]))}
                 for day, values in sorted(months.items())]
        seasonal_weight = (sum(forecast.seasonality[day.month - 1] for day in dates) / horizon)
        explanation = (
            f"Прогноз на {horizon} дн.: {forecast_total:.2f} {product.base_unit}; "
            f"страховой запас на {safety_days} дн.: {safety:.2f}. "
            f"Доступно {available:.2f}, подтверждено в пути в пределах горизонта {sum(receipts):.2f}. "
            f"Потребность с учётом дат: {raw:.2f}; с MOQ и кратностью: {recommended} {product.base_unit}."
        )
        if before_arrival > 1e-8:
            explanation += f" До прибытия возможна потеря {before_arrival:.2f} единиц спроса; она не добавлена как задолженность."
        recommendations.append({
            "id": f"{product.sku}|{inventory.warehouse_id}", "sku": product.sku, "name": product.name,
            "unit": product.base_unit, "warehouse_id": inventory.warehouse_id,
            "category_id": product.category_id, "supplier_id": supplier.supplier_id,
            "supplier_name": supplier.supplier_name, "recommended_qty": float(recommended),
            "recommended_qty_exact": str(recommended),
            "urgency": urgency, "available_stock": _number(available), "inbound_qty": _number(sum(receipts)),
            "forecast_demand": _number(forecast_total), "safety_stock": _number(safety),
            "raw_requirement": _number(raw), "balance_requirement": _number(balance_need),
            "timing_adjustment": _number(raw - balance_need),
            "rounding_adjustment": _number(float(recommended) - raw), "lead_time_days": lead,
            "horizon_days": horizon, "base_daily_demand": _number(forecast.base_daily_demand),
            "seasonality_factor": _number(seasonal_weight), "growth_pct": _number(forecast.growth_pct),
            "moq": float(moq), "order_multiple": float(multiple),
            "moq_exact": str(moq), "order_multiple_exact": str(multiple), "stockout_days": stockout_days,
            "estimated_lost_demand": _number(estimated_lost) if use_stockout else 0.0,
            "excluded_qty": _number(excluded_qty) if use_outliers else 0.0,
            "excluded_events": sum(event["excluded"] for event in product_events) if use_outliers else 0,
            "data_warnings": warnings,
            "explanation_steps": [
                {"label": "Прогноз спроса", "value": _number(forecast_total)},
                {"label": "Страховой запас", "value": _number(safety)},
                {"label": "Доступный остаток", "value": -_number(available)},
                {"label": "Поставки в горизонте", "value": -_number(sum(receipts))},
                {"label": "Минимум ноль", "value": _number(balance_need - (forecast_total + safety - available - sum(receipts)))},
                {"label": "Корректировка по датам", "value": _number(raw - balance_need)},
                {"label": "MOQ и кратность", "value": _number(float(recommended) - raw)},
            ],
            "explanation": explanation, "chart": chart,
            "projection": [{"date": day.isoformat(), "demand": _number(demands[index]),
                            "stock_without_order": _number(without[index]),
                            "stock_with_order": _number(with_order[index]),
                            "inbound": _number(receipts[index]),
                            "new_order": float(recommended) if index == lead else 0.0,
                            "lost_without_order": _number(lost_without[index]),
                            "lost_with_order": _number(lost_with[index])}
                           for index, day in enumerate(dates)],
            "seasonality": [_number(value) for value in forecast.seasonality],
            "events": [dict(event, excluded=event["excluded"] and use_outliers) for event in product_events],
            "shortage_date": dates[first_shortage].isoformat() if first_shortage is not None else None,
            "unmet_demand_before_arrival": _number(before_arrival),
            "seasonality_source": forecast.seasonality_source, "forecast_source": forecast.level_source,
            "trend_source": forecast.trend_source,
            "shipments": sorted(shipments, key=lambda s: (s["date"], s["id"])),
            "policy": {"review_days": review_days, "safety_days": safety_days, "arrival_date": (as_of + timedelta(days=lead)).isoformat(),
                       "stockout_correction": use_stockout, "outlier_exclusion": use_outliers,
                       "seasonality": use_seasonality, "trend": use_trend,
                       "demand_semantics": "lost_sales", "trend_cap_30d_pct": [-20, 30],
                       "trend_extrapolation_days": 90},
        })
    priorities = {"critical": 0, "review": 1, "order_now": 2, "reserve": 3, "none": 4}
    recommendations.sort(key=lambda row: (priorities[row["urgency"]], row["supplier_id"], row["sku"], row["warehouse_id"]))
    return {"recommendations": recommendations, "summary": {
        "positions": len(recommendations), "order_positions": sum(row["recommended_qty"] > 0 for row in recommendations),
        "critical_count": sum(row["urgency"] == "critical" for row in recommendations),
        "review_count": sum(row["urgency"] == "review" for row in recommendations),
        "supplier_count": len({row["supplier_id"] for row in recommendations if row["recommended_qty"] > 0}),
        "stockout_days": sum(row["stockout_days"] for row in recommendations),
        "excluded_events": sum(row["excluded_events"] for row in recommendations),
        "as_of_date": as_of.isoformat(), "algorithm_version": "explainable-statistics-1.0",
    }}
