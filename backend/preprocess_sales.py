"""Load validated canonical CSVs, prepare sales and export a separate audit trail."""

import argparse
import csv
import json
import sys
from pathlib import Path

from backend.app.engine.contracts import DatasetContext, parse_date
from backend.app.engine.preprocessing.models import PreparationConfig, PreparedDay
from backend.app.engine.preprocessing.report import generate_preprocessing_report
from backend.app.engine.preprocessing.sales_cleaning import prepare_sales
from backend.app.modules.imports.csv_loader import load_csv_dataset


def export_prepared(prepared, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    with (output / "daily_demand.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(PreparedDay.model_fields), lineterminator="\n")
        writer.writeheader()
        for day in prepared.daily:
            row = day.model_dump(mode="json")
            for field in ("sale_line_ids", "reasons"):
                row[field] = json.dumps(row[field], ensure_ascii=False)
            writer.writerow(row)
    for name, records in (("normalized_sales.jsonl", prepared.normalized_sales), ("customer_events.jsonl", prepared.events)):
        with (output / name).open("w", encoding="utf-8", newline="") as stream:
            for record in records:
                stream.write(record.model_dump_json() + "\n")
    report = generate_preprocessing_report(prepared)
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--output", type=Path, default=Path("data/preprocessed"))
    parser.add_argument("--as-of-date", default="2026-09-01")
    parser.add_argument("--history-start", default="2024-09-01")
    parser.add_argument("--history-end", default="2026-08-31")
    parser.add_argument("--cutoff-date", help="Inclusive historical cutoff; later sales are ignored")
    parser.add_argument("--split-window-days", type=int, default=5)
    args = parser.parse_args()
    try:
        source, target = args.input.resolve(), args.output.resolve()
        if source == target or source in target.parents or target in source.parents:
            raise ValueError("Output must be separate from input and its parent/child directories")
        context = DatasetContext(as_of_date=args.as_of_date, history_start=args.history_start, history_end=args.history_end)
        result = load_csv_dataset(source, context)
        if not result.report.valid:
            print(result.report.model_dump_json(indent=2), file=sys.stderr)
            return 1
        prepared = prepare_sales(result.dataset, parse_date(args.cutoff_date) if args.cutoff_date else None,
                                 PreparationConfig(split_window_days=args.split_window_days))
        print(json.dumps(export_prepared(prepared, target), indent=2))
    except (ValueError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
