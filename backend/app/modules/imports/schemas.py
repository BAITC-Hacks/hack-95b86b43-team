"""Import diagnostics; invalid partial data is never published as InputDataset."""

from datetime import date
from pydantic import BaseModel, Field

from backend.app.engine.contracts import InputDataset


class ValidationIssue(BaseModel):
    code: str
    file: str
    row: int | None = None
    field: str | None = None
    message: str


class ValidationReport(BaseModel):
    valid: bool = False
    schema_version: str = "1.0"
    as_of_date: date | None = None
    row_counts: dict[str, int] = Field(default_factory=dict)
    accepted_row_counts: dict[str, int] = Field(default_factory=dict)
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class LoadResult(BaseModel):
    dataset: InputDataset | None
    report: ValidationReport
