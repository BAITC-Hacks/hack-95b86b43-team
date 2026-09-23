"""Deterministic monthly-demand models; no external coefficients are inferred."""
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

D = Decimal
ALGORITHM_VERSION = "robust-monthly-2"


@dataclass(frozen=True)
class ForecastResult:
    daily: tuple[Decimal, ...]
    method: str
    history_months: int
    seasonal_indices: tuple[Decimal, ...]
    monthly_trend: Decimal
    explanation_steps: tuple[dict, ...]
    limitations: tuple[str, ...]


def shift_month(value: date, offset: int) -> date:
    year, month = divmod(value.year * 12 + value.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def complete_history(history, calculation_date, minimum=6, maximum=36):
    """Use a contiguous past suffix. Missing or negative recent months block a model."""
    rows, limitations = [], []
    for offset in range(1, maximum + 1):
        period = shift_month(calculation_date, -offset)
        value = history.get(period)
        valid = isinstance(value, D) and value.is_finite() and value >= 0
        if not valid:
            if len(rows) < minimum:
                raise ValueError(f"Missing/negative history requires review for {period.isoformat()}")
            limitations.append(f"History stops before missing/negative month {period.isoformat()}")
            break
        rows.append((period, value / D(monthrange(period.year, period.month)[1])))
    return list(reversed(rows)), limitations


def robust_daily(history: dict[date, Decimal | None], calculation_date: date, horizon: int,
                 external_growth: Decimal | None = None, growth_mode: str | None = None,
                 fallback_seasonality: tuple[Decimal, ...] | None = None) -> ForecastResult:
    """Two-cycle seasonality, confirmed recent trend, and an intermittent mean model.

    All parameters are heuristic and exposed in the explanation; this is not a fitted ML model.
    Growth is a scenario multiplier over the horizon, not an annual growth rate.
    """
    if type(horizon) is not int or horizon <= 0:
        raise ValueError("Horizon must be a positive integer")
    if external_growth is not None:
        if not isinstance(external_growth, D) or not external_growth.is_finite() or external_growth < -1:
            raise ValueError("External growth must be a finite fraction >= -1")
        if growth_mode not in {"replace", "additional"}:
            raise ValueError("Choose replace or additional for external growth")
    elif growth_mode is not None:
        raise ValueError("Growth mode requires an explicit external growth")
    if fallback_seasonality is not None:
        if len(fallback_seasonality) != 12 or any(not isinstance(v, D) or not v.is_finite() or v <= 0 for v in fallback_seasonality):
            raise ValueError("A confirmed seasonal profile must contain 12 positive Decimal indices")
    rows, limitations = complete_history(history, calculation_date)
    rates = [value for _, value in rows]
    indices = [D(1)] * 12
    intermittent = sum(value == 0 for value in rates) * 2 >= len(rates)
    seasonal_source = "none"
    if not intermittent and len(rows) >= 24 and all(value > 0 for value in rates):
        # Same-calendar-month ratios remove recurring seasonality before detrending.
        annual_logs = [(rates[i] / rates[i - 12]).ln() / 12 for i in range(12, len(rates))]
        drift = max(-D("1.05").ln(), min(D("1.05").ln(), median(annual_logs)))
        detrended = [value / (drift * D(i - len(rates) + 1)).exp() for i, value in enumerate(rates)]
        for month in range(1, 13):
            group = [value for (period, _), value in zip(rows, detrended) if period.month == month]
            # With only two observations, a lone large event is not evidence of recurring seasonality.
            if len(group) == 2 and max(group) > min(group) * 3:
                indices[month - 1] = min(group)
                limitations.append(f"Inconsistent seasonal observations for month {month}; lower level used")
            else:
                indices[month - 1] = median(group)
        scale = sum(indices) / 12
        indices = [value / scale for value in indices]
        seasonal_source = "sku_complete_months"
    elif not intermittent and fallback_seasonality is not None:
        scale = sum(fallback_seasonality) / 12
        indices = [value / scale for value in fallback_seasonality]
        seasonal_source = "explicit_confirmed_profile"
    else:
        limitations.append("SKU seasonality unavailable; neutral indices used")
    deseasonal = [value / indices[period.month - 1] for period, value in rows]
    trend = D(1)
    if not intermittent and all(value > 0 for value in deseasonal[-6:]):
        changes = [deseasonal[i] / deseasonal[i - 1] for i in range(len(rows) - 5, len(rows))]
        # Four of five successive changes must agree; a single peak cannot establish a trend.
        if sum(value > D("1.005") for value in changes) >= 4 or sum(value < D("0.995") for value in changes) >= 4:
            trend = max(D(1) / D("1.05"), min(D("1.05"), median(changes)))
    if intermittent:
        # Event frequency × average positive size equals the mean, with explicit zero months included.
        level = sum(rates[-12:]) / len(rates[-12:])
        method = "intermittent_frequency_size"
    else:
        level = median([deseasonal[-1 - lag] * trend ** lag for lag in range(3)])
        method = "robust_seasonal_trend"
    applied_trend = D(1) if growth_mode == "replace" else trend
    multiplier = D(1) if external_growth is None else D(1) + external_growth
    reference = rows[-1][0]
    values = []
    for offset in range(horizon):
        day = calculation_date + timedelta(days=offset)
        distance = (day.year - reference.year) * 12 + day.month - reference.month
        # Extrapolation is capped at six calendar months beyond the observed history.
        values.append(level * indices[day.month - 1] * applied_trend ** min(distance, 6) * multiplier)
    steps = ({"operation": "forecast_model", "version": ALGORITHM_VERSION, "method": method,
              "history_start": rows[0][0], "history_end": reference, "history_months": len(rows)},
             {"operation": "seasonality", "source": seasonal_source, "indices": tuple(indices)},
             {"operation": "trend", "estimated_monthly_factor": trend, "applied_monthly_factor": applied_trend,
              "required_consistent_changes": 4, "maximum_monthly_factor": D("1.05"), "projection_cap_months": 6},
             {"operation": "external_growth", "fraction": external_growth, "mode": growth_mode, "multiplier": multiplier},
             {"operation": "forecast_total", "reference_daily_level": level, "value": sum(values)})
    return ForecastResult(tuple(values), method, len(rows), tuple(indices), trend, steps, tuple(limitations))


def backtest_monthly(history, calculation_date, origins=6):
    """Expanding-origin validation. No future actuals/coefficients enter a fitted model."""
    rows, _ = complete_history(history, calculation_date)
    periods = [period for period, _ in rows]
    predictions = {name: [] for name in (ALGORITHM_VERSION, "simple_mean", "seasonal_naive")}
    for period in periods[max(6, len(periods) - origins):]:
        training = {p: history[p] for p in periods if p < period}
        days = monthrange(period.year, period.month)[1]
        forecast = robust_daily(training, period, days)
        actual = history[period]
        predictions[ALGORITHM_VERSION].append((actual, sum(forecast.daily), days))
        recent = sorted(training)[-6:]
        mean_rate = sum(training[p] / D(monthrange(p.year, p.month)[1]) for p in recent) / len(recent)
        predictions["simple_mean"].append((actual, mean_rate * days, days))
        previous = shift_month(period, -12)
        if previous in training:
            predictions["seasonal_naive"].append((actual, training[previous] / D(monthrange(previous.year, previous.month)[1]) * days, days))
    metrics = {}
    for name, pairs in predictions.items():
        if not pairs:
            metrics[name] = {"origins": 0, "mae": None, "wape": None, "bias": None, "daily_rmse": None}
            continue
        errors = [predicted - actual for actual, predicted, _ in pairs]
        total = sum(actual for actual, _, _ in pairs)
        metrics[name] = {"origins": len(pairs), "mae": sum(abs(e) for e in errors) / len(errors),
                         "wape": sum(abs(e) for e in errors) / total if total else None,
                         "bias": sum(errors) / len(errors),
                         "daily_rmse": (sum(((predicted - actual) / days) ** 2 for actual, predicted, days in pairs) / len(pairs)).sqrt()}
    return metrics


def error_safety_stock(metrics, horizon: int, service_z: Decimal) -> Decimal:
    """Scenario approximation: perfectly correlated daily forecast error within horizon."""
    if type(horizon) is not int or horizon <= 0 or not isinstance(service_z, D) or not service_z.is_finite() or service_z < 0:
        raise ValueError("Invalid horizon or category service factor")
    if metrics["origins"] < 3 or metrics["daily_rmse"] is None:
        raise ValueError("At least three retrospective origins required for error-based safety stock")
    return service_z * metrics["daily_rmse"] * horizon


def baseline_daily(history: dict[date, Decimal | None], calculation_date: date,
                   horizon: int, window: int = 6) -> tuple[Decimal, ...]:
    """Use exactly the last N full calendar months; do not fill missing periods."""
    if horizon <= 0 or window <= 0:
        raise ValueError("Horizon and history window must be positive")
    cursor = calculation_date.replace(day=1)
    rates = []
    for _ in range(window):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        quantity = history.get(cursor)
        if quantity is None:
            raise ValueError(f"Unknown history for {cursor.isoformat()}")
        if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
            raise ValueError(f"Negative/invalid net sales require review for {cursor.isoformat()}")
        rates.append(quantity / Decimal(monthrange(cursor.year, cursor.month)[1]))
    return (median(rates),) * horizon
