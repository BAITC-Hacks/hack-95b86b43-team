"""Composable demand preparation and replenishment, independent of storage and HTTP."""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal as D

from .contracts import ReplenishmentInput, ReplenishmentResult
from .forecast import ALGORITHM_VERSION, ForecastResult, robust_daily, backtest_monthly, error_safety_stock
from .outliers import Sale, OutlierResult, detect_outliers, cleaned_daily
from .stockouts import StockoutInterval, StockoutResult, restore_stockouts, daily_to_monthly
from .replenishment import calculate


@dataclass(frozen=True)
class PreparedDemand:
    monthly: dict[date, D | None]
    outliers: OutlierResult
    excluded_quantity: D
    stockouts: StockoutResult


@dataclass(frozen=True)
class CategoryPolicy:
    name: str
    service_z: D


@dataclass(frozen=True)
class DemandRecommendation:
    forecast: ForecastResult
    backtest: dict
    category: CategoryPolicy
    replenishment: ReplenishmentResult


def prepare_demand(sales: tuple[Sale, ...], start: date, as_of: date, absolute_minimum: D,
                   confirmed_ids: frozenset[str], stockouts: tuple[StockoutInterval, ...] = (), *,
                   coverage_complete: bool, weights=None, category_daily=None) -> PreparedDemand:
    scoped = tuple(s for s in sales if start <= s.day < as_of)
    outliers = detect_outliers(scoped, as_of, absolute_minimum)
    daily, removed = cleaned_daily(scoped, start, as_of, outliers, confirmed_ids, coverage_complete=coverage_complete)
    restored = restore_stockouts(daily, stockouts, as_of, weights, category_daily)
    if restored.unresolved_days:
        raise ValueError("Confirmed stockout days remain unestimated; demand needs review")
    return PreparedDemand(daily_to_monthly(restored.daily, as_of), outliers, removed, restored)


def recommend(history, inputs: ReplenishmentInput, category: CategoryPolicy,
              external_growth=None, growth_mode=None, fallback_seasonality=None) -> DemandRecommendation:
    horizon = inputs.lead_days + inputs.review_days
    forecast = robust_daily(history, inputs.calculation_date, horizon, external_growth, growth_mode, fallback_seasonality)
    metrics = backtest_monthly(history, inputs.calculation_date)
    safety = error_safety_stock(metrics[ALGORITHM_VERSION], horizon, category.service_z)
    replenishment = calculate(replace(inputs, daily_forecast=forecast.daily, safety_stock=safety))
    step = {"operation": "category_safety_stock", "category": category.name, "service_z": category.service_z,
            "daily_rmse": metrics[ALGORITHM_VERSION]["daily_rmse"], "horizon_days": horizon,
            "assumption": "daily forecast errors fully correlated within horizon", "value": safety}
    replenishment = replace(replenishment, explanation_steps=forecast.explanation_steps + (step,) + replenishment.explanation_steps,
                            limitations=forecast.limitations + replenishment.limitations)
    return DemandRecommendation(forecast, metrics, category, replenishment)
