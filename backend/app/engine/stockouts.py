"""Availability and causal stockout estimates, with no synthetic metadata access."""

from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from backend.app.engine.contracts import Stockout
from backend.app.engine.preprocessing.models import PreparationConfig

Observation = tuple[date, Decimal]


def mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values) if values else Decimal(0)


def stockout_calendar(intervals: list[Stockout], start: date, cutoff: date) -> set[tuple[date, str, str]]:
    unavailable = set()
    for interval in intervals:
        if interval.end_date_exclusive <= interval.start_date:
            raise ValueError("Invalid stockout interval")
        day = max(start, interval.start_date)
        stop = min(cutoff + timedelta(days=1), interval.end_date_exclusive)
        while day < stop:
            unavailable.add((day, interval.sku, interval.warehouse_id))
            day += timedelta(days=1)
    return unavailable


def recent_observations(history: list[Observation], day: date, config: PreparationConfig) -> list[Observation]:
    oldest = day - timedelta(days=config.max_history_age_days)
    return [(d, q) for d, q in history if oldest <= d < day][-config.recent_days:]


def estimate_stockout_demand(history: list[Observation], day: date, peer_histories: list[list[Observation]],
                            config: PreparationConfig) -> dict:
    """Only real, available, non-excluded prior days can be donors; never imputed days."""
    recent = recent_observations(history, day, config)
    weekdays = [(d, q) for d, q in recent if d.weekday() == day.weekday()]
    peers = []
    for history in peer_histories:
        observations = recent_observations(history, day, config)
        if len(observations) >= config.min_recent_days:
            peers.append(observations)
    method, chosen, peer_count = "zero_history", [], 0
    estimate = Decimal(0)
    if len(weekdays) >= config.min_weekday_days:
        chosen, method = weekdays, f"weekday_{config.recent_days}d"
        estimate = min(mean([q for _, q in weekdays]), mean([q for _, q in recent]) * 3)
    elif len(recent) >= config.min_recent_days:
        chosen, method = recent, f"recent_{config.recent_days}d"
        estimate = mean([q for _, q in recent])
    elif peers:
        method, peer_count = "category_fallback", len(peers)
        estimate = median([mean([q for _, q in history]) for history in peers])
        chosen = [observation for history in peers for observation in history]
        # Category peers have different scales. Bound their influence when own evidence exists.
        if recent:
            estimate = min(estimate, 3 * mean([q for _, q in recent]))
    elif recent:
        chosen, method = recent, f"recent_{config.recent_days}d"
        estimate = mean([q for _, q in recent])
    latest = max((d for d, _ in chosen), default=None)
    stale = latest is not None and (day - latest).days > config.recent_days
    return {"estimated_demand": max(Decimal(0), estimate), "estimation_method": method,
            "estimation_sample_count": len(chosen), "estimation_peer_count": peer_count,
            "latest_donor_date": latest,
            "insufficient_history": len(recent) < config.min_recent_days or stale}
