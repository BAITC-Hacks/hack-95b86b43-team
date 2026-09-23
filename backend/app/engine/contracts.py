"""Typed inputs use storage units unless explicitly named order units."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Inbound:
    expected_date: date
    quantity: Decimal
    confirmed: bool = True


@dataclass(frozen=True)
class ReplenishmentInput:
    calculation_date: date
    lead_days: int
    review_days: int
    daily_forecast: tuple[Decimal, ...]
    available_stock: Decimal | None
    safety_stock: Decimal
    inbound: tuple[Inbound, ...]
    storage_units_per_order_unit: Decimal | None
    minimum_order: Decimal | None
    order_multiple: Decimal | None


@dataclass(frozen=True)
class ReplenishmentResult:
    status: str
    forecast_demand: Decimal
    eligible_inbound: Decimal
    raw_requirement: Decimal | None
    order_quantity: Decimal | None
    first_deficit_date: date | None
    urgency: str
    explanation_steps: tuple[dict, ...]
    limitations: tuple[str, ...]
