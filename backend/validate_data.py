"""Validate a canonical CSV directory and print one JSON report to stdout."""

import argparse

from pydantic import ValidationError

from backend.app.engine.contracts import DatasetContext
from backend.app.modules.imports.csv_loader import validate_directory
from backend.app.modules.imports.schemas import ValidationIssue, ValidationReport


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--history-start", required=True)
    parser.add_argument("--history-end", required=True)
    args = parser.parse_args()
    try:
        context = DatasetContext(
            as_of_date=args.as_of_date, history_start=args.history_start, history_end=args.history_end,
        )
    except ValidationError as exc:
        report = ValidationReport(errors=[
            ValidationIssue(code="INVALID_CONTEXT", file="<arguments>",
                            field=".".join(map(str, item["loc"])) or "history_period",
                            message=item["msg"])
            for item in exc.errors(include_url=False, include_input=False)
        ])
    else:
        report = validate_directory(args.input, context)
    print(report.model_dump_json(indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
