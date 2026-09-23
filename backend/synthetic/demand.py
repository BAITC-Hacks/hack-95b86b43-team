"""Known data-generating process, not a forecasting algorithm."""

import math
from datetime import date
from random import Random


CATEGORIES = ["Кабель", "Автоматы", "Светильники", "Розетки", "Щитовое оборудование", "Монтажные аксессуары"]
SCENARIO_COUNTS = {"stable": 36, "seasonal": 24, "growth": 18, "intermittent": 18, "declining": 12, "new": 12}
PROFILES = {
    "flat": [1.0] * 12,
    "winter": [1.5, 1.4, 1.15, .9, .8, .7, .7, .75, .9, 1.1, 1.35, 1.5],
    "summer": [.65, .7, .85, 1.0, 1.25, 1.5, 1.6, 1.45, 1.15, .9, .75, .7],
    "spring_autumn": [.7, .8, 1.2, 1.5, 1.3, .8, .7, .8, 1.3, 1.5, 1.2, .8],
}


def poisson(rng: Random, mean: float) -> int:
    # Independent Poisson chunks prevent exp underflow for a large gamma draw.
    total = 0
    while mean > 0:
        chunk = min(mean, 20.0)
        threshold, product, count = math.exp(-chunk), 1.0, 0
        while product > threshold:
            product *= rng.random()
            count += 1
        total += count - 1
        mean -= chunk
    return total


def expected_units(spec: dict, day: date, warehouse_scale: float, start: date, end: date) -> float:
    if spec["scenario_type"] == "intermittent":
        return .06 * 3.5 * warehouse_scale
    profile = PROFILES[spec["seasonal_profile"]]
    season = profile[day.month - 1] / (sum(profile) / 12)
    # At default 24 months: smooth +60% growth or -35% decline, not an abrupt jump.
    elapsed_months = (day - start).days / 30.4375
    monthly_multiplier = spec["monthly_multiplier"]
    return spec["base_daily_units"] * warehouse_scale * season * monthly_multiplier ** elapsed_months


def draw_units(rng: Random, spec: dict, expected: float) -> int:
    if spec["scenario_type"] == "intermittent":
        return rng.randint(1, 6) if rng.random() < expected / 3.5 else 0
    shape = 3.0 if spec["sku"] in {"00001", "00002", "00003"} else .65
    # Gamma-Poisson mixture = negative binomial, variance = mean + mean^2 / shape.
    return poisson(rng, rng.gammavariate(shape, expected / shape)) if expected > 0 else 0
