"""Small, explainable demand model. Only validated, historical observations enter it.

No file access, model service, or synthetic ground truth is used here. Quantities
are normalized before category pooling, so meters are never added to pieces.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import exp, log
from statistics import mean, median

from backend.app.engine.contracts import InputDataset
from backend.app.engine.preprocessing.models import PreparedDay, PreparedSales


@dataclass
class Forecast:
    base_daily_demand: float
    seasonality: list[float]
    log_daily_growth: float
    growth_pct: float
    seasonality_source: str
    level_source: str
    trend_source: str
    warnings: list[str]
    needs_review: bool
    historical: list[tuple[PreparedDay, float | None]]

    def demand(self, day: date, as_of_date: date) -> float:
        age = (day - as_of_date).days
        # A long lead time must not compound a noisy short trend for a year.
        trend_days = min(max(age, 0), 90)
        return max(0.0, self.base_daily_demand * self.seasonality[day.month - 1]
                   * exp(self.log_daily_growth * trend_days))


def _selected_history(days: list[PreparedDay], use_stockout: bool,
                      use_outliers: bool) -> list[tuple[PreparedDay, float | None]]:
    """Scenario switches change the actual model inputs, not only labels.

    In the unfiltered scenario, outage donors are recalculated from past raw
    available days. Imputed days are never fed back as real donor observations.
    """
    result = []
    donors: list[tuple[date, float]] = []
    for day in sorted(days, key=lambda row: row.date):
        if day.demand_status == "STOCKOUT_SALES_CONFLICT":
            result.append((day, None))
            continue
        if day.availability:
            selected = day.demand_for_baseline if use_outliers else day.observed_sales
            # Preserve signed returns here; floor at aggregate level, not per sale.
            value = float(selected) if selected is not None else None
            if value is not None:
                donors.append((day.date, max(0.0, value)))
        elif not use_stockout:
            value = float(day.observed_sales)
        elif use_outliers:
            value = float(day.demand_for_baseline) if day.demand_for_baseline is not None else None
        else:
            recent = [(d, q) for d, q in donors if 0 < (day.date - d).days <= 90][-28:]
            weekdays = [q for d, q in recent if d.weekday() == day.date.weekday()]
            if len(weekdays) >= 4:
                value = min(mean(weekdays), mean(q for _, q in recent) * 3)
            elif recent:
                value = mean(q for _, q in recent)
            else:
                value = float(day.estimated_demand or 0)
            value = max(0.0, value - float(day.return_qty))
        result.append((day, value))
    return result


def _monthly_profile(history: list[tuple[PreparedDay, float | None]]) -> list[float] | None:
    """Detrend matched month pairs, then normalize each SKU's monthly rates.

    At least two observations of every calendar month and 14 available days per
    month are required. Missing or censored months never become artificial zeros.
    """
    months: dict[tuple[int, int], list[float]] = defaultdict(list)
    for day, value in history:
        if day.availability and value is not None:
            months[day.date.year, day.date.month].append(value)
    rates = {key: max(0.0, mean(values)) for key, values in months.items() if len(values) >= 14}
    if any(sum(month == m for _, month in rates) < 2 for m in range(1, 13)):
        return None
    annual_growth = [log(rate / rates[year - 1, month]) / 365.25
                     for (year, month), rate in rates.items()
                     if rate > 0 and rates.get((year - 1, month), 0) > 0]
    daily_growth = median(annual_growth) if len(annual_growth) >= 6 else 0.0
    daily_growth = min(log(2) / 365.25, max(log(0.5) / 365.25, daily_growth))
    center = mean(date(year, month, 15).toordinal() for year, month in rates)
    monthly = defaultdict(list)
    for (year, month), rate in rates.items():
        adjusted = rate / exp(daily_growth * (date(year, month, 15).toordinal() - center))
        monthly[month].append(adjusted)
    profile = [median(monthly[m]) for m in range(1, 13)]
    level = mean(profile)
    if level <= 0:
        return None
    # This bound is a stated demo safeguard, not an inferred service guarantee.
    bounded = [min(2.5, max(0.25, q / level)) for q in profile]
    normalizer = mean(bounded)
    return [q / normalizer for q in bounded]


def _growth(history: list[tuple[PreparedDay, float | None]], seasonal: list[float],
            cutoff: date) -> float:
    """Theil-Sen-like median log slope of weekly, deseasonalized observed rates."""
    weeks = defaultdict(list)
    for day, value in history:
        age = (cutoff - day.date).days
        if 0 <= age < 84 and day.availability and value is not None:
            weeks[age // 7].append(value / seasonal[day.date.month - 1])
    points = sorted((-7 * bucket - 3, max(0.0, mean(values)))
                    for bucket, values in weeks.items() if len(values) >= 5)
    if len(points) < 8 or sum(q > 0 for _, q in points) < 8:
        return 0.0
    slopes = [log(q2 / q1) / (d2 - d1)
              for i, (d1, q1) in enumerate(points) for d2, q2 in points[i + 1:]
              if q1 > 0 and q2 > 0]
    slope = median(slopes) if slopes else 0.0
    if abs(slope) < log(1.02) / 30:
        return 0.0
    support = sum(s * slope > 0 for s in slopes) / len(slopes)
    older, recent = median(q for _, q in points[:4]), median(q for _, q in points[-4:])
    if support < 0.7 or (recent - older) * slope <= 0:
        return 0.0
    return min(log(1.3) / 30, max(log(0.8) / 30, slope))


def _monthly_growth(history: list[tuple[PreparedDay, float | None]], seasonal: list[float]) -> float:
    """Slow growth can be visible over two years but indistinguishable in 12 weeks.

    Use at least 18 monthly observations as a conservative fallback. Monthly
    aggregation reduces daily transaction noise without inventing observations.
    """
    months = defaultdict(list)
    for day, value in history:
        if day.availability and value is not None:
            months[day.date.year, day.date.month].append(value / seasonal[day.date.month - 1])
    points = sorted((date(year, month, 15).toordinal(), max(0.0, mean(values)))
                    for (year, month), values in months.items() if len(values) >= 14)
    if len(points) < 18 or sum(q > 0 for _, q in points) < 18:
        return 0.0
    slopes = [log(q2 / q1) / (d2 - d1)
              for index, (d1, q1) in enumerate(points) for d2, q2 in points[index + 1:]
              if q1 > 0 and q2 > 0]
    slope = median(slopes)
    if abs(slope) < log(1.005) / 30 or sum(s * slope > 0 for s in slopes) / len(slopes) < 0.7:
        return 0.0
    if (median(q for _, q in points[-3:]) - median(q for _, q in points[:3])) * slope <= 0:
        return 0.0
    return min(log(1.3) / 30, max(log(0.8) / 30, slope))


def fit_forecasts(dataset: InputDataset, prepared: PreparedSales, *, use_stockout: bool = True,
                  use_outliers: bool = True, use_seasonality: bool = True,
                  use_trend: bool = True) -> dict[tuple[str, str], Forecast]:
    """Fit all pairs before filtering, so category fallback keeps its peer data."""
    if prepared.cutoff_date != dataset.context.history_end:
        raise ValueError("Prepared cutoff must equal dataset history_end; rebuild for this snapshot")
    cutoff = dataset.context.history_end
    as_of = dataset.context.as_of_date
    products = {p.sku: p for p in dataset.products}
    grouped = defaultdict(list)
    for day in prepared.daily:
        if dataset.context.history_start <= day.date <= cutoff and day.sku in products:
            grouped[day.sku, day.warehouse_id].append(day)
    for stock in dataset.inventory:
        grouped.setdefault((stock.sku, stock.warehouse_id), [])
    histories = {pair: _selected_history(days, use_stockout, use_outliers)
                 for pair, days in grouped.items()}
    own_profiles = {pair: _monthly_profile(history) for pair, history in histories.items()}
    by_category = defaultdict(list)
    for pair, profile in own_profiles.items():
        if profile is not None:
            # These are dimensionless normalized shapes, not pooled quantities.
            by_category[products[pair[0]].category_id].append(profile)
    category_profiles = {}
    for category, profiles in by_category.items():
        merged = [median(profile[m] for profile in profiles) for m in range(12)]
        category_profiles[category] = [q / mean(merged) for q in merged]
    result = {}
    for pair, history in histories.items():
        product = products[pair[0]]
        warnings = []
        if not use_seasonality:
            seasonal, source = [1.0] * 12, "disabled"
        elif own_profiles[pair] is not None:
            seasonal, source = own_profiles[pair], "sku"
        elif product.category_id in category_profiles:
            seasonal, source = category_profiles[product.category_id], "category"
            warnings.append("Сезонность взята из нормированного профиля категории: собственной истории недостаточно.")
        else:
            seasonal, source = [1.0] * 12, "neutral"
            warnings.append("Двух полных сезонных циклов нет: сезонный коэффициент принят равным 1.")
        slope = _growth(history, seasonal, cutoff) if use_trend else 0.0
        trend_source = "recent_weeks" if slope else "none"
        if use_trend and not slope:
            slope = _monthly_growth(history, seasonal)
            if slope:
                trend_source = "monthly_history"
        recent = [(day, value) for day, value in history
                  if (cutoff - day.date).days < 56 and value is not None]
        observed_count = sum(bool(day.availability) for day, _ in recent)
        level_values = [value / seasonal[day.date.month - 1]
                        / exp(slope * (day.date - as_of).days) for day, value in recent]
        level = max(0.0, mean(level_values)) if level_values else 0.0
        needs_review = observed_count < 7
        level_source = "sku"
        if needs_review:
            warnings.append("Менее 7 наблюдаемых дней за последние 56 дней: нужна проверка менеджера.")
        if len(recent) < 7:
            peer_levels = []
            for peer, peer_history in histories.items():
                peer_product = products[peer[0]]
                if (peer == pair or peer[1] != pair[1] or peer_product.category_id != product.category_id
                        or peer_product.base_unit != product.base_unit):
                    continue
                values = [value / seasonal[day.date.month - 1] for day, value in peer_history
                          if day.availability and value is not None and 0 <= (cutoff - day.date).days < 56]
                if len(values) >= 14:
                    peer_levels.append(max(0.0, mean(values)))
            if peer_levels:
                fallback = median(peer_levels)
                # Some own evidence should constrain the scale of peer substitution.
                level = min(fallback, level * 3) if level > 0 else fallback
                level_source, slope = "category_same_unit", 0.0
                trend_source = "none"
                warnings.append("Уровень спроса оценён по товарам категории в той же единице и на том же складе.")
            else:
                warnings.append("Недостаточно подходящих товаров для оценки уровня: использована доступная собственная история.")
        if any(day.demand_status == "STOCKOUT_SALES_CONFLICT" for day, _ in history):
            warnings.append("Есть противоречие между продажами и stockout: такие дни исключены из прогноза.")
            needs_review = True
        if any(not day.availability and day.insufficient_history for day, _ in recent) and use_stockout:
            warnings.append("Часть недавнего скрытого спроса оценена при недостатке наблюдений.")
        result[pair] = Forecast(level, list(seasonal), slope, (exp(slope * 30) - 1) * 100,
                                source, level_source, trend_source, warnings, needs_review, history)
    return result
