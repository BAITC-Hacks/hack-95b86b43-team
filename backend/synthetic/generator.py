"""Deterministic benchmark with isolated truth and a reconciled stock ledger."""

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from random import Random

from backend.app.engine.contracts import DatasetContext
from backend.app.modules.imports.csv_loader import TABLE_MODELS, validate_directory
from backend.synthetic.demand import CATEGORIES, SCENARIO_COUNTS, draw_units, expected_units


GENERATOR_VERSION = "1.0"
DEFAULT_START = date(2024, 9, 1)
DEFAULT_END = date(2026, 8, 31)
HORIZON_DAYS = 21  # A labelled demo horizon, not an order calculation.
DAY = timedelta(days=1)
TRUTH_FIELDS = ["date", "sku", "warehouse_id", "expected_regular_qty", "regular_demand",
                "recurring_client_demand", "one_off_demand", "true_demand", "observed_sales",
                "lost_regular_demand", "lost_total_demand", "opening_stock", "receipts", "closing_stock"]


@dataclass(frozen=True)
class GenerationConfig:
    seed: int = 42
    start_date: date = DEFAULT_START
    end_date: date = DEFAULT_END

    def __post_init__(self):
        if self.start_date.year < 2000 or self.end_date.year > 2100:
            raise ValueError("Supported dates: years 2000 through 2100")
        if not 180 <= (self.end_date - self.start_date).days + 1 <= 1096:
            raise ValueError("History must contain 180 to 1096 days to fit all benchmark scenarios")

    @property
    def context(self):
        return DatasetContext(as_of_date=self.end_date + DAY,
                              history_start=self.start_date, history_end=self.end_date)


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_table(path: Path, fields: list[str], rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def quantity(units: int, step: Decimal) -> str:
    return format(units * step, "f")


def make_catalog(rng: Random, config: GenerationConfig) -> tuple[dict, list[dict]]:
    tables = {name: [] for name in TABLE_MODELS}
    tables["categories"] = [{"category_id": f"CAT-{i+1:02}", "category_name": name}
                            for i, name in enumerate(CATEGORIES)]
    tables["warehouses"] = [{"warehouse_id": f"WH-{i:02}", "warehouse_name": f"Синтетический склад {i}"}
                            for i in (1, 2)]
    tables["suppliers"] = [{"supplier_id": f"SUP-{i:03}", "supplier_name": f"Синтетический поставщик {i}"}
                           for i in range(1, 9)]
    specs = []
    days = (config.end_date - config.start_date).days + 1
    for scenario, count in SCENARIO_COUNTS.items():
        for _ in range(count):
            index = len(specs)
            sku = f"{index+1:05}"
            category = index % 6
            step = Decimal("0.25") if category == 0 else Decimal("1")
            active = config.start_date
            if scenario == "new":
                active += timedelta(days=rng.randint(int(days * .75), int(days * .9)))
            profile = "flat"
            if scenario == "seasonal":
                profile = ["winter", "summer", "spring_autumn"][(index - 36) % 3]
            multiplier = 1.6 ** (1 / 24) if scenario == "growth" else .65 ** (1 / 24) if scenario == "declining" else 1.0
            base_qty = rng.uniform(.7, 2.0)
            if index < 3:
                base_qty = rng.uniform(12, 18)
            if scenario == "intermittent":
                base_qty = .06 * 3.5 * float(step)
            spec = {"sku": sku, "scenario_type": scenario, "seasonal_profile": profile,
                    "monthly_multiplier": multiplier, "base_daily_units": base_qty / float(step),
                    "active_from": active.isoformat(), "unit_step": str(step),
                    "normal_customer_pool": rng.sample([f"CUST-{i:04}" for i in range(1, 298)], 18)}
            specs.append(spec)
            tables["products"].append({"sku": sku, "name": f"Демо: {CATEGORIES[category]} {index+1:03}",
                "category_id": f"CAT-{category+1:02}", "base_unit": "m" if category == 0 else "pcs",
                "active_from": active.isoformat()})
            tables["product_suppliers"].append({"sku": sku, "supplier_id": f"SUP-{index%8+1:03}",
                "is_primary": "true", "lead_time_days": [7, 10, 14, 21, 28][index % 5],
                "moq": "20" if index % 4 == 0 else "0", "order_multiple": "5" if index % 4 == 0 else str(step)})
    return tables, specs


def make_events(config: GenerationConfig) -> list[dict]:
    span = (config.end_date - config.start_date).days
    event_day = config.start_date + timedelta(days=int(span * .82))
    events = []
    for i, sku in enumerate(("00001", "00002", "00003")):
        split = sku == "00002"
        events.append({"event_id": f"PROJECT-{i+1}", "kind": "one_off_split" if split else "one_off",
            "sku": sku, "warehouse_id": "WH-01", "customer_anon_id": "CUST-0299" if i != 2 else "CUST-0300",
            "parts": [{"date": (event_day + timedelta(days=j // 2)).isoformat(),
                       "qty": "100" if split else str(800 if i == 0 else 750)} for j in range(6 if split else 1)],
            "sale_line_ids": []})
    day = config.start_date
    while day <= config.end_date:
        if day.day == 15:
            events.append({"event_id": f"RECURRING-{day:%Y%m}", "kind": "recurring",
                "sku": "00004", "warehouse_id": "WH-01", "customer_anon_id": "CUST-0298",
                "parts": [{"date": day.isoformat(), "qty": "90"}], "sale_line_ids": []})
        day += DAY
    return events


def make_blackouts(rng: Random, config: GenerationConfig, index: int, warehouse: str) -> list[tuple[date, date]]:
    # The high-volume demonstration SKU and other stable SKUs get both outage lengths.
    if index >= 36 or index % 4 != 0 or warehouse != "WH-01":
        return []
    span = (config.end_date - config.start_date).days
    return [(config.start_date + timedelta(days=int(span * fraction)),
             config.start_date + timedelta(days=int(span * fraction) + rng.randint(*duration)))
            for fraction, duration in ((.35, (5, 10)), (.60, (10, 20)))]


def stock_segments(days: list[date], blackouts: list[tuple[date, date]]):
    """Receipt cadence is 14 days, split at externally imposed supply outages."""
    i = 0
    while i < len(days):
        unavailable = any(start <= days[i] < end for start, end in blackouts)
        j = i + 1
        while j < len(days) and j - i < 14:
            next_unavailable = any(start <= days[j] < end for start, end in blackouts)
            if next_unavailable != unavailable:
                break
            j += 1
        yield i, j, unavailable
        i = j


def generate_dataset(output: Path | str, config: GenerationConfig = GenerationConfig()) -> dict:
    output = Path(output)
    # Only overwrite a previous generated dataset, never a directory of partner CSVs.
    marker = output / "metadata.json"
    if output.exists() and any(output.iterdir()):
        if not marker.exists() or json.loads(marker.read_text(encoding="utf-8")).get("generator") != "hackalem-synthetic":
            raise ValueError("Output is not empty and is not a generated synthetic dataset; choose another directory")
    output.mkdir(parents=True, exist_ok=True)
    truth_dir = output / "metadata"
    truth_dir.mkdir(exist_ok=True)
    rng = Random(config.seed)
    tables, specs = make_catalog(rng, config)
    events = make_events(config)
    event_map = defaultdict(list)
    for event in events:
        for part in event["parts"]:
            event_map[(event["sku"], event["warehouse_id"], part["date"])].append((event, part))
    metadata = {"generator": "hackalem-synthetic", "generator_version": GENERATOR_VERSION,
        "synthetic_only": True, "disclaimer": "Демонстрационная синтетика, не сведения об Электрокомплекте.",
        "seed": config.seed, "history_start": config.start_date.isoformat(), "history_end": config.end_date.isoformat(),
        "as_of_date": config.context.as_of_date.isoformat(), "demo_horizon_days": HORIZON_DAYS,
        "skus": specs, "customers": [f"CUST-{i:04}" for i in range(1, 301)],
        "large_events": events, "stockout_intervals": [], "expected_inbound": [], "inventory_scenarios": [],
        "true_demand": {"file": "metadata/true_demand.csv", "scope": "active SKU x warehouse x day",
            "regular_target": "regular_demand + recurring_client_demand",
            "excluded_from_regular_target": "one_off_demand",
            "note": "Evaluation only. Never supply this file or metadata.json to forecasting."}}
    # A failed run remains visibly invalid; a successful report replaces this marker.
    metadata["validation_valid"] = False
    write_json(marker, metadata)
    write_json(output / "validation-report.json", {"valid": False, "generation_in_progress": True})
    sale_counter = 0
    receipt_counter = 0
    truth_path = truth_dir / "true_demand.csv"
    with truth_path.open("w", encoding="utf-8", newline="") as stream:
        truth_writer = csv.DictWriter(stream, fieldnames=TRUTH_FIELDS, lineterminator="\n")
        truth_writer.writeheader()
        for index, spec in enumerate(specs):
            step = Decimal(spec["unit_step"])
            active = date.fromisoformat(spec["active_from"])
            days = [active + timedelta(days=i) for i in range((config.end_date - active).days + 1)]
            price = str(rng.randint(50, 1500) * 10)
            for warehouse_index, warehouse in enumerate(("WH-01", "WH-02")):
                scale = 1.0 if warehouse_index == 0 else .65
                blackouts = make_blackouts(rng, config, index, warehouse)
                planned = [{"sku": spec["sku"], "warehouse_id": warehouse, "start_date": start.isoformat(),
                            "end_date_exclusive": end.isoformat()} for start, end in blackouts]
                metadata["stockout_intervals"].extend(planned)
                regular, daily_events, expected = [], [], []
                for day in days:
                    mean = expected_units(spec, day, scale, config.start_date, config.end_date)
                    expected.append(mean)
                    regular.append(draw_units(rng, spec, mean))
                    daily_events.append(event_map[(spec["sku"], warehouse, day.isoformat())])
                event_units = [sum(int(Decimal(part["qty"]) / step) for _, part in parts) for parts in daily_events]
                totals = [regular[i] + event_units[i] for i in range(len(days))]
                # Snapshot coverage classes are benchmark parameters, not order recommendations.
                stock_class = ["high", "normal", "low", "zero"][(index + warehouse_index) % 4]
                coverage = {"high": 60, "normal": 20, "low": 2, "zero": 0}[stock_class]
                target = math.ceil(expected[-1] * coverage)
                partial_units = min(target, max(1, int(Decimal("20") / step))) if index == 0 and warehouse_index == 0 else 0
                receipts = [0] * len(days)
                balance = 0
                for first, last, unavailable in stock_segments(days, blackouts):
                    if unavailable:
                        if balance != 0:
                            raise RuntimeError("Synthetic supply plan failed to empty stock before outage")
                        continue
                    # Exact demand is used ONLY by the synthetic supply fixture to guarantee
                    # controlled stockouts. It is never a forecasting input or algorithm.
                    final = last == len(days)
                    next_boundary = next((a for a, _ in blackouts if a >= days[last - 1] + DAY), None)
                    boundary_index = (next_boundary - active).days if next_boundary else len(days)
                    remaining = sum(totals[last:boundary_index])
                    if next_boundary is None:
                        remaining += target - partial_units
                    # Never carry a unit that cannot be consumed before a forced empty
                    # boundary, especially for intermittent zero-demand final weeks.
                    buffer = target - partial_units if final else min(1, remaining)
                    receipt = max(0, sum(totals[first:last]) + buffer - balance)
                    receipts[first] += receipt
                    balance += receipt - sum(totals[first:last])
                receipts[-1] += partial_units
                balance = 0
                zero_start = None
                for i, day in enumerate(days):
                    opening = balance
                    balance += receipts[i]
                    if receipts[i] > (partial_units if i == len(days) - 1 else 0):
                        received = receipts[i] - (partial_units if i == len(days) - 1 else 0)
                        receipt_counter += 1
                        tables["inbound"].append({"po_line_id": f"HIST-{receipt_counter:06}", "sku": spec["sku"],
                            "warehouse_id": warehouse, "supplier_id": tables["product_suppliers"][index]["supplier_id"],
                            "qty_ordered": quantity(received, step), "qty_received": quantity(received, step),
                            "eta": day.isoformat(), "status": "received"})
                    if balance == 0 and zero_start is None:
                        zero_start = day
                    elif balance > 0 and zero_start is not None:
                        tables["stockouts"].append({"sku": spec["sku"], "warehouse_id": warehouse,
                            "start_date": zero_start.isoformat(), "end_date_exclusive": day.isoformat()})
                        zero_start = None
                    sold_regular = min(regular[i], balance)
                    balance -= sold_regular
                    if sold_regular:
                        sale_counter += 1
                        tables["sales"].append({"sale_line_id": f"SALE-{sale_counter:07}", "date": day.isoformat(),
                            "sku": spec["sku"], "warehouse_id": warehouse,
                            "customer_anon_id": rng.choice(spec["normal_customer_pool"]), "qty": quantity(sold_regular, step),
                            "unit_price": price, "operation_type": "sale", "order_id": f"ORDER-{sale_counter:07}"})
                    sold_event, recurring, project = 0, 0, 0
                    lost_recurring = 0
                    for event, part in daily_events[i]:
                        requested = int(Decimal(part["qty"]) / step)
                        sold = min(requested, balance)
                        balance -= sold
                        sold_event += sold
                        if event["kind"] == "recurring":
                            recurring += requested
                            lost_recurring += requested - sold
                        else:
                            project += requested
                        if sold != requested:
                            raise RuntimeError("Showcase client event must be fully observable")
                        sale_counter += 1
                        line_id = f"SALE-{sale_counter:07}"
                        event["sale_line_ids"].append(line_id)
                        # Order identifiers must not leak labels such as PROJECT/RECURRING.
                        event.setdefault("order_id", f"ORDER-{sale_counter:07}")
                        tables["sales"].append({"sale_line_id": line_id, "date": day.isoformat(), "sku": spec["sku"],
                            "warehouse_id": warehouse, "customer_anon_id": event["customer_anon_id"],
                            "qty": quantity(sold, step), "unit_price": price, "operation_type": "sale", "order_id": event["order_id"]})
                    truth_writer.writerow({"date": day.isoformat(), "sku": spec["sku"], "warehouse_id": warehouse,
                        "expected_regular_qty": f"{expected[i] * float(step):.6f}",
                        "regular_demand": quantity(regular[i], step), "recurring_client_demand": quantity(recurring, step),
                        "one_off_demand": quantity(project, step), "true_demand": quantity(totals[i], step),
                        "observed_sales": quantity(sold_regular + sold_event, step),
                        "lost_regular_demand": quantity(regular[i] - sold_regular + lost_recurring, step),
                        "lost_total_demand": quantity(totals[i] - sold_regular - sold_event, step),
                        "opening_stock": quantity(opening, step), "receipts": quantity(receipts[i], step),
                        "closing_stock": quantity(balance, step)})
                if zero_start is not None:
                    tables["stockouts"].append({"sku": spec["sku"], "warehouse_id": warehouse,
                        "start_date": zero_start.isoformat(), "end_date_exclusive": config.context.as_of_date.isoformat()})
                if balance != target:
                    raise RuntimeError("Synthetic inventory does not reconcile")
                tables["inventory"].append({"snapshot_date": config.context.as_of_date.isoformat(), "sku": spec["sku"],
                    "warehouse_id": warehouse, "on_hand": quantity(balance, step),
                    "reserved": quantity(balance // 10, step), "blocked": quantity(balance // 25, step),
                    "availability_start": active.isoformat()})
                metadata["inventory_scenarios"].append({"sku": spec["sku"], "warehouse_id": warehouse,
                    "stock_class": stock_class, "coverage_parameter_days": coverage})
                if partial_units:
                    tables["inbound"].append({"po_line_id": "PARTIAL-001", "sku": spec["sku"], "warehouse_id": warehouse,
                        "supplier_id": tables["product_suppliers"][index]["supplier_id"],
                        "qty_ordered": quantity(partial_units * 4, step), "qty_received": quantity(partial_units, step),
                        "eta": (config.context.as_of_date + timedelta(days=7)).isoformat(), "status": "in_transit"})
    # Outstanding receipts are never included in the historical stock ledger.
    for i in range(24):
        offset = [-3, 5, 12, HORIZON_DAYS + 15][i % 4]
        row = {"po_line_id": f"OPEN-{i+1:03}", "sku": specs[i]["sku"], "warehouse_id": f"WH-{i%2+1:02}",
               "supplier_id": tables["product_suppliers"][i]["supplier_id"], "qty_ordered": str(40 + i * 5),
               "qty_received": "0", "eta": (config.context.as_of_date + timedelta(days=offset)).isoformat(),
               "status": "in_transit" if i % 2 else "confirmed"}
        tables["inbound"].append(row)
    metadata["expected_inbound"] = [row for row in tables["inbound"] if row["status"] != "received"]
    metadata["actual_stockout_intervals"] = tables["stockouts"]
    metadata["partially_received_at"] = config.end_date.isoformat()
    for name, rows in tables.items():
        fields = [field for field in TABLE_MODELS[name].model_fields if field not in {"source_file", "source_row"}]
        write_table(output / f"{name}.csv", fields, rows)
    report = validate_directory(output, config.context)
    write_json(output / "validation-report.json", report.model_dump(mode="json"))
    metadata["validation_valid"] = report.valid
    metadata["summary"] = {
        "sku_count": len(specs), "sales_rows": len(tables["sales"]),
        "customer_count": len({row["customer_anon_id"] for row in tables["sales"]}),
        "stockout_count": len(tables["stockouts"]), "inbound_count": len(tables["inbound"]),
        "scenario_counts": dict(Counter(spec["scenario_type"] for spec in specs)),
        "large_events_count": len(events), "one_off_events_count": sum(e["kind"] != "recurring" for e in events),
        "recurring_events_count": sum(e["kind"] == "recurring" for e in events),
        "history_start": config.start_date.isoformat(), "history_end": config.end_date.isoformat(),
        "as_of_date": config.context.as_of_date.isoformat(), "seed": config.seed,
        "valid": report.valid, "warning_codes": sorted({w.code for w in report.warnings}),
    }
    write_json(marker, metadata)
    if not report.valid:
        raise ValueError("Generated dataset failed validation; see validation-report.json")
    return metadata["summary"]
