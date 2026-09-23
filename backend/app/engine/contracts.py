"""Source-independent input models. No forecasting or file access here."""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def parse_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected date YYYY-MM-DD")
    return date.fromisoformat(value)


def parse_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(\.\d+)?", value):
        raise ValueError("Expected decimal with dot, without separators or exponent")
    return Decimal(value)


def parse_boolean(value: object) -> bool:
    if type(value) is bool:
        return value
    if value not in ("true", "false"):
        raise ValueError("Expected true or false")
    return value == "true"


def parse_days(value: object) -> int:
    if type(value) is int:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d+", value):
        raise ValueError("Expected a non-negative integer")
    return int(value)


Identifier = Annotated[str, Field(strict=True, min_length=1)]
ISODate = Annotated[date, BeforeValidator(parse_date)]
Quantity = Annotated[Decimal, Field(ge=0, allow_inf_nan=False), BeforeValidator(parse_decimal)]
PositiveQuantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False), BeforeValidator(parse_decimal)]
Boolean = Annotated[bool, BeforeValidator(parse_boolean)]
Days = Annotated[int, Field(ge=0), BeforeValidator(parse_days)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file: str
    source_row: int = Field(ge=2)


class Product(Record):
    sku: Identifier
    name: Identifier
    category_id: Identifier
    base_unit: Identifier
    active_from: ISODate


class Category(Record):
    category_id: Identifier
    category_name: Identifier


class Warehouse(Record):
    warehouse_id: Identifier
    warehouse_name: Identifier


class Supplier(Record):
    supplier_id: Identifier
    supplier_name: Identifier


class ProductSupplier(Record):
    sku: Identifier
    supplier_id: Identifier
    is_primary: Boolean
    lead_time_days: Days
    moq: Quantity | None = None
    order_multiple: PositiveQuantity | None = None


class Sale(Record):
    sale_line_id: Identifier
    date: ISODate
    sku: Identifier
    warehouse_id: Identifier
    customer_anon_id: Identifier
    qty: Quantity
    unit_price: Quantity
    operation_type: Literal["sale", "return"]
    order_id: Identifier | None = None


class Inventory(Record):
    snapshot_date: ISODate
    sku: Identifier
    warehouse_id: Identifier
    on_hand: Quantity
    reserved: Quantity
    blocked: Quantity
    availability_start: ISODate | None = None


class Stockout(Record):
    sku: Identifier
    warehouse_id: Identifier
    start_date: ISODate
    end_date_exclusive: ISODate


class Inbound(Record):
    po_line_id: Identifier
    sku: Identifier
    warehouse_id: Identifier
    supplier_id: Identifier
    qty_ordered: Quantity
    qty_received: Quantity
    eta: ISODate
    status: Literal["confirmed", "in_transit", "received", "cancelled"]


class DatasetContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_date: ISODate
    history_start: ISODate
    history_end: ISODate

    @model_validator(mode="after")
    def check_period(self) -> "DatasetContext":
        if self.history_start > self.history_end:
            raise ValueError("history_start must not be after history_end")
        if self.history_end.toordinal() != self.as_of_date.toordinal() - 1:
            raise ValueError("history_end must be the day before as_of_date")
        return self


class InputDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    context: DatasetContext
    products: list[Product] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    warehouses: list[Warehouse] = Field(default_factory=list)
    suppliers: list[Supplier] = Field(default_factory=list)
    product_suppliers: list[ProductSupplier] = Field(default_factory=list)
    sales: list[Sale] = Field(default_factory=list)
    inventory: list[Inventory] = Field(default_factory=list)
    stockouts: list[Stockout] = Field(default_factory=list)
    inbound: list[Inbound] = Field(default_factory=list)
