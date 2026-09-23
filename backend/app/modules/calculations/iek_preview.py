"""IEK scenario wiring; business assumptions stay explicit and auditable."""
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
import re

from ...engine.contracts import Inbound, ReplenishmentInput
from ...engine.forecast import ALGORITHM_VERSION
from ...engine.pipeline import CategoryPolicy, recommend
from ..imports.adapters.iek import read
from ..imports.normalization import number, label
from ..imports.profiling import dumps
from ..imports.validation import normalize_observations
from .preview import write_preview_html

KINDS = {"sales": "sales_monthly", "inventory": "inventory_monthly",
         "inbound": "inbound", "constraints": "constraints"}


def file_sources(root):
    patterns = {"sales": "*продажи в*", "inventory": "*остатки*", "inbound": "Путь*", "constraints": "MOQ*"}
    sources = {}
    for role, pattern in patterns.items():
        paths = list((root / "IEK").glob(pattern + ".xlsx"))
        if len(paths) != 1:
            raise ValueError(f"Expected exactly one IEK {role} workbook")
        sources[role] = []
        for row in read(paths[0]):
            if row.kind == KINDS[role]:
                _, issues = normalize_observations(row, {})
                errors = tuple(message for severity, _, message in issues if severity == "error")
                sources[role].append(replace(row, errors=errors))
    return sources


def origin(row):
    return {"file": row.file, "sha256": row.sha256, "sheet": row.sheet, "row": row.row}


def shipment_inputs(row, policy):
    """Parse arrival date, never the document date; preserve same-day shipments."""
    if row is None:
        if policy.get("missing_inbound_row") == "zero":
            return (), []
        raise ValueError("Inbound row is missing; absence does not prove zero")
    receipts, evidence = [], []
    for heading, raw in sorted(row.fields.items()):
        if "поступление до" not in heading:
            continue
        match = re.search(r"поступление до\s+(\d{2}\.\d{2}\.\d{4})", heading)
        if not match:
            raise ValueError("Inbound arrival date is not recognized")
        arrival = datetime.strptime(match[1], "%d.%m.%Y").date()
        quantity = number(raw)
        if quantity is None:
            if policy.get("blank_inbound_quantity") != "zero":
                raise ValueError("Inbound quantity is unknown")
            quantity = D(0)
        if quantity < 0:
            raise ValueError("Inbound quantity is negative")
        receipts.append(Inbound(arrival, quantity, policy["assume_inbound_confirmed"]))
        evidence.append({"heading": heading, "expected_date": arrival, "quantity": quantity,
                         "confirmed": policy["assume_inbound_confirmed"]})
    if not evidence:
        raise ValueError("No dated inbound columns")
    return tuple(receipts), evidence


def preview_iek(root: Path, policy: dict, output: Path, persisted_sources=None, dataset_id=None):
    required = ("calculation_date", "inventory_month", "stock_mode", "lead_days", "review_days",
                "service_z", "assumptions", "assume_inbound_confirmed", "minimum_unit", "unit_rules")
    if policy.get("mode") != "scenario_on_real_data" or any(k not in policy for k in required):
        raise ValueError("An explicit complete IEK scenario policy is required")
    if not policy["assumptions"] or type(policy["assume_inbound_confirmed"]) is not bool:
        raise ValueError("Document assumptions and provide boolean inbound confirmation")
    z = number(policy["service_z"])
    if z is None or z < 0:
        raise ValueError("service_z must be finite and nonnegative")
    if policy["stock_mode"] not in {"unknown", "historical_opening_proxy", "explicit_snapshot"}:
        raise ValueError("Unknown stock mode")
    if policy["minimum_unit"] not in {"storage", "order"}:
        raise ValueError("MOQ unit must be explicit")
    for field in ("lead_days", "review_days"):
        if type(policy[field]) is not int or policy[field] < 0:
            raise ValueError("Lead/review days must be nonnegative integers")
    if policy["lead_days"] + policy["review_days"] == 0:
        raise ValueError("Empty forecast horizon")
    as_of = date.fromisoformat(policy["calculation_date"])
    inventory_month = date.fromisoformat(policy["inventory_month"])
    if inventory_month.day != 1 or inventory_month > as_of:
        raise ValueError("Inventory month must be a past/current month opening")
    sources = persisted_sources if persisted_sources is not None else file_sources(root)
    indices, duplicates = {}, {}
    for role in KINDS:
        counts = Counter(r.code for r in sources[role])
        duplicates[role] = {code for code, count in counts.items() if count > 1}
        indices[role] = {r.code: r for r in sources[role]}
    result = {"mode": policy["mode"], "policy": policy, "algorithm_version": ALGORITHM_VERSION,
              "limitations": ["Scenario assumptions are unconfirmed; no approved purchase order",
                  "Monthly opening stock is not a current free-stock snapshot",
                  "No document cleaning or stockout restoration on unconfirmed real inputs"],
              "recommendations": []}
    if dataset_id:
        result["dataset_id"] = dataset_id
    for sales in sources["sales"]:
        item = {"supplier": "iek", "code": sales.code, "source": origin(sales)}
        try:
            related = {role: index.get(sales.code) for role, index in indices.items()}
            if not sales.code or any(sales.code in codes for codes in duplicates.values()):
                raise ValueError("Missing or ambiguous product code")
            if any(r.errors for r in related.values() if r is not None):
                raise ValueError("Source row requires review")
            inventory, constraint = related["inventory"], related["constraints"]
            item["sources"] = {role: origin(r) for role, r in related.items() if r is not None}
            item["article"] = constraint.fields.get("артикул поставщика") if constraint else None
            unit = label(inventory.fields.get("ед.", inventory.fields.get("ед.изм"))) if inventory else ""
            rule = policy.get("products", {}).get(sales.code, policy["unit_rules"].get(unit, {}))
            conversion = number(rule.get("storage_units_per_order_unit"))
            if rule and label(rule.get("storage_unit")) != unit:
                raise ValueError("Unit rule conflicts with source storage unit")
            # Never infer a reel length from a name, nor allow a generic metre rule.
            if unit in {"м", "м.", "метр"} and sales.code not in policy.get("products", {}):
                conversion = None
            item.update(storage_unit=unit or None, order_unit=rule.get("order_unit"), unit_rule=rule)
            if conversion is not None and (conversion <= 0 or not rule.get("order_unit")):
                raise ValueError("Positive conversion and explicit order unit required")
            stock = None
            stock_evidence = {"mode": policy["stock_mode"], "source_month": inventory_month,
                              "historical_opening": inventory.fields.get(inventory_month.isoformat()) if inventory else None}
            if policy["stock_mode"] == "historical_opening_proxy":
                stock = stock_evidence["historical_opening"]
                stock_evidence["warning"] = "Historical total opening stock used as free-stock proxy; no roll-forward or reserve inference"
            elif policy["stock_mode"] == "explicit_snapshot":
                snapshot = policy.get("snapshots", {}).get(sales.code)
                if snapshot:
                    if snapshot.get("date") != as_of.isoformat() or label(snapshot.get("storage_unit")) != unit:
                        raise ValueError("Snapshot date/unit conflicts with calculation")
                    stock = number(snapshot.get("available_stock"))
                    stock_evidence["snapshot"] = snapshot
            item["stock_input"] = stock_evidence
            inbound, item["inbound_inputs"] = shipment_inputs(related["inbound"], policy)
            minimum = constraint.fields.get("мин. разр. к отгр.") if constraint else None
            if minimum is not None and policy["minimum_unit"] == "storage":
                minimum = minimum / conversion if conversion else None
            history = {date.fromisoformat(k): v for k, v in sales.fields.items() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", k)}
            inputs = ReplenishmentInput(as_of, policy["lead_days"], policy["review_days"], (), stock, D(0),
                inbound, conversion, minimum, number(rule.get("order_multiple")))
            recommendation = recommend(history, inputs, CategoryPolicy("explicit_scenario", z))
            item.update(asdict(recommendation.replenishment))
            item["forecast_diagnostics"] = {"method": recommendation.forecast.method,
                "history_months": recommendation.forecast.history_months, "backtest": recommendation.backtest}
            if policy["stock_mode"] == "historical_opening_proxy":
                item["limitations"] += (stock_evidence["warning"],)
        except ValueError as exc:
            item.update(status="insufficient_data", order_quantity=None, limitations=[str(exc)])
        result["recommendations"].append(item)
    result["unmatched_codes"] = {role: sorted(set(index) - set(indices["sales"]) - {None})
                                  for role, index in indices.items() if role != "sales"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dumps(result) + "\n", encoding="utf-8")
    write_preview_html(result, output.with_suffix(".html"))
    return result
