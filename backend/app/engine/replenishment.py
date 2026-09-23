"""Pure replenishment arithmetic and time-phased shortage detection."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
import sys
from pathlib import Path

try:
    from .contracts import ReplenishmentInput, ReplenishmentResult
except ImportError:  # pragma: no cover - direct script execution fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.engine.contracts import ReplenishmentInput, ReplenishmentResult

ZERO = Decimal(0)


def calculate(inputs: ReplenishmentInput) -> ReplenishmentResult:
    for field, value in (("lead_days", inputs.lead_days), ("review_days", inputs.review_days)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{field} must be a nonnegative integer")

    horizon = inputs.lead_days + inputs.review_days
    if horizon <= 0 or len(inputs.daily_forecast) != horizon:
        raise ValueError("Daily forecast must cover exactly lead_days + review_days")

    values = (*inputs.daily_forecast, inputs.safety_stock, *(p.quantity for p in inputs.inbound))
    if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in values):
        raise ValueError("Forecast, safety stock and inbound must be finite nonnegative Decimals")

    for name, value, strictly_positive in (
        ("available_stock", inputs.available_stock, False),
        ("conversion", inputs.storage_units_per_order_unit, True),
        ("minimum_order", inputs.minimum_order, False),
        ("order_multiple", inputs.order_multiple, True),
    ):
        if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
            raise ValueError(f"{name} must be a finite Decimal")
        if value is not None and name != "available_stock" and (value < 0 or (strictly_positive and value == 0)):
            raise ValueError(f"Invalid {name}")

    start = inputs.calculation_date
    end = start + timedelta(days=horizon)
    eligible = [p for p in inputs.inbound if p.confirmed and start <= p.expected_date < end]
    inbound_total = sum((p.quantity for p in eligible), ZERO)
    demand = sum(inputs.daily_forecast, ZERO)
    limitations = []

    if any(p.expected_date < start and p.quantity > 0 for p in inputs.inbound):
        limitations.append("Overdue inbound excluded until its expected date is confirmed")

    steps = [{
        "operation": "horizon_days",
        "lead_days": inputs.lead_days,
        "review_days": inputs.review_days,
        "value": horizon,
    }, {
        "operation": "forecast_demand",
        "value": demand,
    }, {
        "operation": "eligible_inbound",
        "value": inbound_total,
    }]

    if inputs.available_stock is None:
        return ReplenishmentResult(
            "insufficient_data",
            demand,
            inbound_total,
            None,
            None,
            None,
            "unknown",
            tuple(steps),
            tuple(limitations + ["Available stock is unknown"]),
        )

    raw = max(ZERO, demand + inputs.safety_stock - inputs.available_stock - inbound_total)
    balance, deficit = inputs.available_stock, None
    if balance < 0:
        deficit = start

    for day, daily_demand in enumerate(inputs.daily_forecast):
        current = start + timedelta(days=day)
        balance += sum((p.quantity for p in eligible if p.expected_date == current), ZERO)
        balance -= daily_demand
        if balance < 0 and deficit is None:
            deficit = current

    arrival = start + timedelta(days=inputs.lead_days)
    urgency = "expedite" if deficit is not None and deficit < arrival else "planned" if deficit else "no_shortage"

    steps.append({
        "operation": "max_zero_demand_plus_safety_minus_stock_minus_inbound",
        "demand": demand,
        "safety_stock": inputs.safety_stock,
        "available_stock": inputs.available_stock,
        "inbound": inbound_total,
        "value": raw,
    })

    if raw == 0:
        quantity = ZERO
    elif any(v is None for v in (inputs.storage_units_per_order_unit, inputs.minimum_order, inputs.order_multiple)):
        return ReplenishmentResult(
            "insufficient_data",
            demand,
            inbound_total,
            raw,
            None,
            deficit,
            urgency,
            tuple(steps),
            tuple(limitations + ["Conversion, minimum order or multiple is unknown"]),
        )
    else:
        in_order_units = raw / inputs.storage_units_per_order_unit
        quantity = (
            max(in_order_units, inputs.minimum_order) / inputs.order_multiple
        ).to_integral_value(rounding=ROUND_CEILING) * inputs.order_multiple
        steps.append({
            "operation": "convert_apply_minimum_round_up",
            "requirement_in_order_units": in_order_units,
            "conversion": inputs.storage_units_per_order_unit,
            "minimum": inputs.minimum_order,
            "multiple": inputs.order_multiple,
            "value": quantity,
        })

    steps.append({"operation": "order_quantity", "value": quantity})
    return ReplenishmentResult(
        "calculated",
        demand,
        inbound_total,
        raw,
        quantity,
        deficit,
        urgency,
        tuple(steps),
        tuple(limitations),
    )
