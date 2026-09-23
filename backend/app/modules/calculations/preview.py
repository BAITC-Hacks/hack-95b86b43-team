"""A diagnostic first pass on Systeme sources with explicit scenario assumptions.

This does not activate a dataset or create an approved order.
"""
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from html import escape
import json

from ...engine.contracts import Inbound, ReplenishmentInput
from ...engine.forecast import baseline_daily
from ...engine.replenishment import calculate
from ..imports.adapters.systeme import read
from ..imports.profiling import dumps


def preview(root: Path, policy: dict, output: Path) -> dict:
    if policy.get("mode") != "scenario_on_real_data":
        raise ValueError("Preview requires an explicitly labelled scenario_on_real_data policy")
    required = ("calculation_date", "assumed_stock_date", "inbound_date", "lead_days", "review_days",
                "safety_stock_days", "minimum_order", "storage_units_per_order_unit", "order_unit",
                "constraint_source", "assumptions")
    if any(k not in policy for k in required):
        raise ValueError("Incomplete scenario policy")
    if policy["constraint_source"] != "dedicated_moq":
        raise ValueError("Supported explicit priority: dedicated_moq")
    as_of = date.fromisoformat(policy["calculation_date"])
    if date.fromisoformat(policy["assumed_stock_date"]) != as_of:
        raise ValueError("Preview stock date must equal calculation date; no silent stock roll-forward")
    if not policy["assumptions"]:
        raise ValueError("Scenario assumptions must be documented")
    files = sorted((root / "Systeme electric").glob("*.xlsx"))
    moq_files = [p for p in files if p.name.startswith("MOQ")]
    summary_files = [p for p in files if p.name.startswith("Товар в пути")]
    if len(moq_files) != 1 or len(summary_files) != 1:
        raise ValueError("Expected one dedicated MOQ and one Systeme summary")
    constraints, duplicate_codes = {}, set()
    for row in read(moq_files[0]):
        if row.kind == "constraints" and row.code:
            if row.code in constraints:
                duplicate_codes.add(row.code)
            constraints[row.code] = row
    rows = [r for r in read(summary_files[0]) if r.kind == "summary"]
    from collections import Counter
    code_counts = Counter(r.code for r in rows if r.code)
    result = {"mode": policy["mode"], "policy": policy, "algorithm_version": "baseline-1",
              "limitations": ["Scenario only; stock date, coverage, units and supply policy are unconfirmed",
                  "Baseline median of six complete monthly daily rates; no seasonality, trend or stockout correction",
                  "External growth/category codes retained but not interpreted",
                  "No order approval or export; this file is a diagnostic calculation"], "recommendations": []}
    for row in rows:
        item = {"code": row.code, "supplier": "systeme", "source": {
            "file": row.file, "sheet": row.sheet, "row": row.row, "sha256": row.sha256},
            "order_unit": policy["order_unit"], "category_raw": row.fields.get("категория 2026"),
            "article": row.fields.get("артикул поставщика")}
        try:
            if row.errors or not row.code:
                raise ValueError("Source row requires review")
            if code_counts[row.code] != 1 or row.code in duplicate_codes:
                raise ValueError("Ambiguous product code")
            constraint = constraints.get(row.code)
            if constraint and constraint.errors:
                raise ValueError("Constraint row requires review")
            fields = row.fields
            history = {date.fromisoformat(k): v for k, v in fields.items() if len(k) == 10 and k[4] == "-"}
            forecast = baseline_daily(history, as_of, policy["lead_days"] + policy["review_days"])
            qty = fields.get("сэ в пути 24.09")
            if qty is None:
                raise ValueError("Inbound quantity is unknown")
            inputs = ReplenishmentInput(as_of, policy["lead_days"], policy["review_days"], forecast,
                fields.get("свободный остаток"), forecast[0] * Decimal(str(policy["safety_stock_days"])),
                (Inbound(date.fromisoformat(policy["inbound_date"]), qty),),
                Decimal(str(policy["storage_units_per_order_unit"])), Decimal(str(policy["minimum_order"])),
                constraint.fields.get("кратность") if constraint else None)
            calculated = calculate(inputs)
            item.update(asdict(calculated))
            item["forecast_daily"] = forecast[0]
            if constraint:
                item["constraint_source"] = {"file": constraint.file, "sheet": constraint.sheet,
                                             "row": constraint.row, "sha256": constraint.sha256}
        except ValueError as exc:
            item.update(status="insufficient_data", order_quantity=None, limitations=[str(exc)])
        result["recommendations"].append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dumps(result) + "\n", encoding="utf-8")
    write_preview_html(result, output.with_suffix(".html"))
    return result


def write_preview_html(result: dict, path: Path) -> None:
    """A standalone diagnostic table, explicitly separate from order export."""
    def text(value):
        return escape("—" if value is None else str(value))

    rows = []
    for item in result["recommendations"]:
        status = "Рассчитано в сценарии" if item["status"] == "calculated" else "Недостаточно данных"
        details = {k: item.get(k) for k in ("source", "constraint_source", "explanation_steps", "limitations")}
        rows.append("<tr>" + "".join(f"<td>{text(item.get(k))}</td>" for k in
            ("code", "article", "forecast_demand", "eligible_inbound", "raw_requirement", "order_quantity", "first_deficit_date"))
            + f"<td>{status}<details><summary>Обоснование</summary><pre>{escape(dumps(details))}</pre></details></td></tr>")
    html = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Systeme Electric — диагностический расчёт</title>
<style>body{font:15px system-ui;margin:24px;color:#17212b}h1{font-size:24px}
.notice{background:#fff3cf;padding:16px;border-left:4px solid #9b6500}table{border-collapse:collapse;width:100%}
th,td{padding:10px;border-bottom:1px solid #dde1e5;text-align:left;vertical-align:top}th{background:#eef2f6;position:sticky;top:0}
td:nth-child(n+3):nth-child(-n+6){text-align:right;font-variant-numeric:tabular-nums}
.table{overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:560px;font-size:12px}
</style><h1>Systeme Electric: первый расчёт</h1>
<p class="notice">Демонстрационный сценарий на реальных исходниках. Условия закупки и охват не подтверждены.
Это диагностическая таблица, не утверждённый заказ. Прогноз — медиана суточных темпов за шесть полных месяцев;
сезонность, рост, категории и stockout пока не учитываются.</p>
"""
    html += "<details><summary>Все допущения сценария</summary><pre>" + escape(
        json.dumps(result["policy"], ensure_ascii=False, indent=2)) + "</pre></details>"
    html += f'<p>Дата расчёта: {text(result["policy"]["calculation_date"])}. Строк: {len(rows)}. Количество заказа — в единицах, заданных в сценарии.</p>'
    html += '<div class="table"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in
        ("Код 1С", "Артикул", "Прогноз на горизонт", "Учтённый путь", "Потребность до округления", "Количество заказа", "Первый дефицит", "Статус"))
    html += "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></html>"
    path.write_text(html, encoding="utf-8")
