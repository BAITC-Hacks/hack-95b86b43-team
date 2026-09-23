"""CSV adapter. Parsing retains source lines and reports every rejected row."""

import csv
from pathlib import Path

from pydantic import ValidationError

from backend.app.engine.contracts import (
    Category, DatasetContext, Inbound, InputDataset, Inventory, Product,
    ProductSupplier, Record, Sale, Stockout, Supplier, Warehouse,
)
from backend.app.modules.imports.schemas import LoadResult, ValidationIssue, ValidationReport
from backend.app.modules.imports.validation import validate_dataset


TABLE_MODELS = {
    "products": Product,
    "categories": Category,
    "warehouses": Warehouse,
    "suppliers": Supplier,
    "product_suppliers": ProductSupplier,
    "sales": Sale,
    "inventory": Inventory,
    "stockouts": Stockout,
    "inbound": Inbound,
}
SOURCE_FIELDS = {"source_file", "source_row"}
EMPTY_ALLOWED = {"sales", "stockouts", "inbound"}


def read_csv_table(path: Path, model: type[Record], report: ValidationReport) -> list[Record]:
    records = []
    report.row_counts[path.name] = 0
    report.accepted_row_counts[path.name] = 0

    def error(code: str, message: str, row: int | None = None, field: str | None = None):
        report.errors.append(ValidationIssue(
            code=code, file=path.name, row=row, field=field, message=message,
        ))

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if not header:
                error("MISSING_HEADER", "CSV must contain a header", 1)
                return records
            allowed = set(model.model_fields) - SOURCE_FIELDS
            required = {name for name in allowed if model.model_fields[name].is_required()}
            if len(header) != len(set(header)):
                error("DUPLICATE_COLUMN", "Column names must be unique", 1)
                return records
            missing = sorted(required - set(header))
            unknown = sorted(set(header) - allowed)
            for name in missing:
                error("MISSING_COLUMN", "Required column is missing", 1, name)
            for name in unknown:
                error("UNKNOWN_COLUMN", "Column is not part of this CSV contract", 1, name)
            header_valid = not missing and not unknown
            while True:
                line = reader.line_num + 1
                values = next(reader, None)
                if values is None:
                    break
                report.row_counts[path.name] += 1
                if len(values) != len(header):
                    error("ROW_WIDTH", "Row length does not match header", line)
                    continue
                if not header_valid:
                    continue
                data = dict(zip(header, values))
                for name, value in data.items():
                    if value != value.strip():
                        error("SURROUNDING_WHITESPACE", "Remove surrounding whitespace explicitly", line, name)
                # Only explicitly optional empty fields become None, never numeric zero.
                for name in allowed - required:
                    if data.get(name) == "":
                        data[name] = None
                try:
                    records.append(model.model_validate({
                        **data, "source_file": path.name, "source_row": line,
                    }))
                except ValidationError as exc:
                    for issue in exc.errors(include_url=False, include_input=False):
                        field = ".".join(str(part) for part in issue["loc"])
                        error("INVALID_VALUE", issue["msg"], line, field)
    except FileNotFoundError:
        error("MISSING_FILE", "Required CSV file is missing")
    except UnicodeError:
        error("INVALID_ENCODING", "CSV must use UTF-8 (BOM allowed)")
    except csv.Error as exc:
        error("INVALID_CSV", str(exc), reader.line_num)
    except OSError as exc:
        error("FILE_READ_ERROR", f"Cannot read CSV: {exc.strerror}")
    report.accepted_row_counts[path.name] = len(records)
    return records


def load_csv_dataset(directory: Path | str, context: DatasetContext) -> LoadResult:
    directory = Path(directory)
    report = ValidationReport(as_of_date=context.as_of_date)
    tables = {}
    for name, model in TABLE_MODELS.items():
        tables[name] = read_csv_table(directory / f"{name}.csv", model, report)
        if not tables[name] and name not in EMPTY_ALLOWED:
            report.errors.append(ValidationIssue(
                code="EMPTY_TABLE", file=f"{name}.csv",
                message="This table must contain at least one valid record",
            ))
    partial = InputDataset(context=context, **tables)
    validate_dataset(partial, report)
    report.valid = not report.errors
    return LoadResult(dataset=partial if report.valid else None, report=report)


def validate_directory(directory: Path | str, context: DatasetContext) -> ValidationReport:
    return load_csv_dataset(directory, context).report
