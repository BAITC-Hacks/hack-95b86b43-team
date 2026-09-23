"""Reproducible, explicitly synthetic acceptance scenarios; no partner data is read."""
from calendar import monthrange
from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from random import Random
import csv

from ...engine.contracts import ReplenishmentInput, Inbound
from ...engine.forecast import ALGORITHM_VERSION, shift_month, robust_daily
from ...engine.outliers import Sale, detect_outliers
from ...engine.stockouts import StockoutInterval, daily_to_monthly
from ...engine.pipeline import prepare_demand, recommend, CategoryPolicy
from ..imports.profiling import dumps
from .preview import write_preview_html

AS_OF = date(2026, 1, 1)
START = date(2023, 1, 1)
SEED = 42
SEASONAL_PROFILE = tuple(map(D, ("0.6", "0.6", "0.8", "1", "1.2", "1.4", "1.6", "1.4", "1.2", "1", "0.7", "0.5")))


def monthly_fixture(seasonal=False, growth=D(1), seed=SEED, noisy=False, intermittent=False):
    random = Random(seed)
    history = {}
    for i in range(36):
        period = shift_month(START, i)
        rate = D(10) * growth ** i
        if seasonal:
            rate *= SEASONAL_PROFILE[period.month - 1]
        if noisy:
            rate += random.randint(-3, 3)
        if intermittent:
            rate = D(30) if random.randrange(4) == 0 else D(0)
        history[period] = rate * monthrange(period.year, period.month)[1]
    return history


def transaction_fixture(kind):
    intervals = tuple(StockoutInterval(date(2025, m, 10), date(2025, m, 20)) for m in (10, 11, 12)) if kind == "stockout" else ()
    sales = []
    for i in range((AS_OF - START).days):
        day = START + timedelta(days=i)
        quantity = D(0) if any(interval.start <= day < interval.end for interval in intervals) else D(10)
        if kind == "stockout" and day == date(2025, 12, 10):
            quantity = D(3)  # Already observed demand must not be added a second time.
        sales.append(Sale(day, f"ordinary-{day.isoformat()}", quantity, "SYNTHETIC", "total"))
    project_docs = set()
    if kind in {"outlier_document", "outlier_split"}:
        parts = 1 if kind == "outlier_document" else 5
        for i in range(parts):
            document = f"project-{i}"
            sales.append(Sale(date(2025, 11, 15), document, D(200) / parts,
                              "SYNTHETIC", "total", "anonymous-project"))
            project_docs.add(document)
    return tuple(sales), intervals, project_docs


def replenishment_fixture():
    return ReplenishmentInput(AS_OF, 14, 7, (), D(20), D(0),
                             (Inbound(date(2026, 1, 5), D(10)),), D(1), D(0), D(1))


def run_demo(output: Path, seed=SEED):
    policy = {"calculation_date": AS_OF.isoformat(), "seed": seed, "order_unit": "synthetic units",
              "assumptions": ["All data is synthetic; no real inventory or customer records are used",
                "Project documents are confirmed using known synthetic labels, not automatic removal",
                "Stockout intervals and complete transaction coverage are known by construction",
                "Category service factors are illustrative; estimated service levels are not guaranteed"]}
    result = {"mode": "synthetic", "algorithm_version": ALGORITHM_VERSION, "policy": policy,
              "limitations": ["Forecast validation and diagnostic export, not an approved supplier order"],
              "recommendations": []}
    cases = ("ordinary", "seasonal", "growth", "intermittent", "category_error",
             "outlier_document", "outlier_split", "stockout", "late_inbound")
    for index, name in enumerate(cases):
        adjustments, steps, limits = {}, (), ()
        history = monthly_fixture(seasonal=name == "seasonal", growth=D("1.02") if name == "growth" else D(1),
                                  noisy=name == "category_error", intermittent=name == "intermittent", seed=seed)
        if name in {"outlier_document", "outlier_split", "stockout"}:
            sales, intervals, true_project_docs = transaction_fixture(name)
            detection = detect_outliers(sales, AS_OF, D(100))
            confirmed = frozenset(c.id for c in detection.candidates if set(c.documents).issubset(true_project_docs))
            prepared = prepare_demand(sales, START, AS_OF, D(100), confirmed, intervals, coverage_complete=True)
            history = prepared.monthly
            raw_daily = {START + timedelta(days=i): D(0) for i in range((AS_OF - START).days)}
            for sale in sales:
                raw_daily[sale.day] += sale.quantity
            raw_forecast = robust_daily(daily_to_monthly(raw_daily, AS_OF), AS_OF, 21)
            adjustments = {"candidates": [asdict(c) for c in detection.candidates], "confirmed_ids": sorted(confirmed),
                "excluded_quantity": prepared.excluded_quantity, "stockout_added": sum(prepared.stockouts.added.values()),
                "unresolved_days": len(prepared.stockouts.unresolved_days), "raw_forecast_demand": sum(raw_forecast.daily),
                "stockout_daily_adjustments": [{"date": day, "added": qty} for day, qty in prepared.stockouts.added.items()]}
            steps = ({"operation": "confirmed_project_exclusion", "value": prepared.excluded_quantity},
                     {"operation": "stockout_compensation", "value": sum(prepared.stockouts.added.values())})
            limits = prepared.outliers.limitations + prepared.stockouts.limitations
        inputs = replenishment_fixture()
        if name == "late_inbound":
            inputs = replace(inputs, available_stock=D(0), inbound=(Inbound(date(2026, 1, 20), D(1000)),))
        category = CategoryPolicy("synthetic_priority" if name == "category_error" else "synthetic_standard",
                                  D("2.0") if name == "category_error" else D("1.0"))
        prediction = recommend(history, inputs, category)
        item = {"supplier": "systeme" if index % 2 == 0 else "iek", "code": name, "article": "synthetic",
                "order_unit": "synthetic units", **asdict(prediction.replenishment),
                "forecast_diagnostics": {"method": prediction.forecast.method, "backtest": prediction.backtest},
                "demand_adjustments": adjustments}
        item["explanation_steps"] = steps + prediction.replenishment.explanation_steps
        item["limitations"] = limits + prediction.replenishment.limitations
        result["recommendations"].append(item)
    result["recommendations"].sort(key=lambda row: (row["supplier"], row["code"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dumps(result) + "\n", encoding="utf-8")
    write_preview_html(result, output.with_suffix(".html"))
    # Diagnostic CSV only; the order-approval/export workflow remains a separate task.
    with output.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ("mode", "supplier", "code", "order_quantity", "order_unit", "explanation")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in result["recommendations"]:
            writer.writerow({"mode": "synthetic_diagnostic", "supplier": item["supplier"], "code": item["code"],
                "order_quantity": item["order_quantity"], "order_unit": item["order_unit"],
                "explanation": dumps(item["explanation_steps"])})
    return result
