"""Compensate only confirmed absence intervals, without re-adding observed sales."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal as D
from statistics import median


@dataclass(frozen=True)
class StockoutInterval:
    start: date
    end: date  # Exclusive.
    confirmed: bool = True


@dataclass(frozen=True)
class StockoutResult:
    daily: dict[date, D | None]
    added: dict[date, D]
    unresolved_days: tuple[date, ...]
    limitations: tuple[str, ...]


def restore_stockouts(daily: dict[date, D | None], intervals: tuple[StockoutInterval, ...], as_of: date,
                      weights: dict[date, D] | None = None, category_daily: D | None = None,
                      lookback_days: int = 56, minimum_peers: int = 3) -> StockoutResult:
    if type(lookback_days) is not int or type(minimum_peers) is not int or lookback_days < 1 or minimum_peers < 1:
        raise ValueError("Invalid comparison window")
    if category_daily is not None and (not isinstance(category_daily, D) or not category_daily.is_finite() or category_daily < 0):
        raise ValueError("Category fallback must be a finite nonnegative daily rate")
    observed = {day: value for day, value in daily.items() if day < as_of}
    if any(value is not None and (not isinstance(value, D) or not value.is_finite() or value < 0) for value in observed.values()):
        raise ValueError("Invalid daily sales")
    absent = set()
    limitations = []
    for interval in intervals:
        if type(interval.confirmed) is not bool:
            raise ValueError("Stockout confirmation must be an explicit boolean")
        if interval.end <= interval.start:
            raise ValueError("Stockout intervals must have positive duration")
        if not interval.confirmed:
            limitations.append("Unconfirmed stockout interval ignored")
            continue
        end = min(interval.end, as_of)
        absent.update(interval.start + timedelta(days=i) for i in range(max(0, (end - interval.start).days)))
    if weights is None and absent:
        limitations.append("No verified seasonal/trend weights; comparable weekdays used with neutral weights")

    def weight(day):
        value = D(1) if weights is None else weights.get(day)
        if value is None or not isinstance(value, D) or not value.is_finite() or value <= 0:
            return None
        return value

    restored, added, unresolved = dict(observed), {}, []
    for day in sorted(absent):
        actual, target_weight = observed.get(day), weight(day)
        if actual is None or target_weight is None:
            unresolved.append(day)
            continue
        peers = [value / weight(peer) for peer, value in observed.items()
                 if 0 < (day - peer).days <= lookback_days and peer.weekday() == day.weekday()
                 and peer not in absent and value is not None and weight(peer) is not None]
        expected = median(peers) * target_weight if len(peers) >= minimum_peers else (
            category_daily * target_weight if category_daily is not None else None)
        if expected is None:
            unresolved.append(day)
            continue
        extra = max(D(0), expected - actual)
        restored[day] = actual + extra
        added[day] = extra
    if unresolved:
        limitations.append("Some confirmed stockout days cannot be estimated from available evidence")
    return StockoutResult(restored, added, tuple(unresolved), tuple(limitations))


def daily_to_monthly(daily: dict[date, D | None], as_of: date) -> dict[date, D | None]:
    """Only complete calendar months. A missing day makes that month's quantity unknown."""
    from calendar import monthrange
    months = defaultdict(dict)
    for day, value in daily.items():
        if day < as_of.replace(day=1):
            months[day.replace(day=1)][day] = value
    result = {}
    for period, days in months.items():
        values = [days.get(period + timedelta(days=i)) for i in range(monthrange(period.year, period.month)[1])]
        result[period] = None if any(v is None for v in values) else sum(values, D(0))
    return result
