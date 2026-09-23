"""Initial baseline. Seasonality, trend and stockout are not implemented yet."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from statistics import median


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
