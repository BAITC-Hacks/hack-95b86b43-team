from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.engine.contracts import Sale


class PreparationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    recent_days: int = Field(default=28, ge=7, le=90)
    max_history_age_days: int = Field(default=90, ge=28, le=365)
    min_recent_days: int = Field(default=7, ge=1)
    min_weekday_days: int = Field(default=4, ge=2)
    min_detection_days: int = Field(default=28, ge=7)
    min_positive_days: int = Field(default=6, ge=2)
    split_window_days: int = Field(default=5, ge=3, le=7)
    relative_days_threshold: Decimal = Field(default=Decimal("8"), gt=0)
    mad_multiplier: Decimal = Field(default=Decimal("8"), gt=0)
    tail_multiplier: Decimal = Field(default=Decimal("4"), gt=0)
    exclusion_peak_multiplier: Decimal = Field(default=Decimal("4"), gt=1)


class NormalizedSale(BaseModel):
    original: Sale
    signed_qty: Decimal
    is_technical_duplicate: bool = False
    event_id: str | None = None
    is_outlier: bool = False
    is_large_customer_event: bool = False
    is_excluded_from_baseline: bool = False
    reasons: list[str] = Field(default_factory=list)


class DailySales(BaseModel):
    date: date
    sku: str
    warehouse_id: str
    gross_sales_qty: Decimal = Decimal(0)
    return_qty: Decimal = Decimal(0)
    net_sales_qty: Decimal = Decimal(0)
    transaction_count: int = 0
    unique_customers: int = 0
    max_single_customer_qty: Decimal = Decimal(0)
    sale_line_ids: list[str] = Field(default_factory=list)


class PreparedDay(DailySales):
    availability: Literal[0, 1]
    observed_sales: Decimal
    estimated_demand: Decimal | None
    demand_for_baseline: Decimal | None
    demand_status: Literal["AVAILABLE", "STOCKOUT", "STOCKOUT_SALES_CONFLICT"]
    estimation_method: str
    estimation_sample_count: int = 0
    estimation_peer_count: int = 0
    latest_donor_date: date | None = None
    insufficient_history: bool = False
    excluded_sales_qty: Decimal = Decimal(0)
    excluded_return_qty: Decimal = Decimal(0)
    is_large_customer_event: bool = False
    is_outlier: bool = False
    is_excluded_from_baseline: bool = False
    reasons: list[str] = Field(default_factory=list)


class CustomerEventAssessment(BaseModel):
    event_id: str
    date: date  # Information cutoff of this immutable assessment.
    start_date: date
    sku: str
    warehouse_id: str
    customer_anon_id: str
    order_ids: list[str]
    sale_line_ids: list[str]  # Only rows known by this assessment date.
    actual_qty: Decimal
    current_day_qty: Decimal
    typical_qty: Decimal
    threshold_qty: Decimal
    exclusion_threshold_qty: Decimal
    large_event_score: Decimal
    relative_to_daily_demand: Decimal | None
    history_days: int
    customer_previous_orders: int
    customer_mean_qty: Decimal
    customer_median_qty: Decimal
    customer_max_qty: Decimal
    is_large_customer_event: bool
    is_outlier: bool
    is_excluded_from_baseline: bool
    large_event_reason: str


class PreparedSales(BaseModel):
    algorithm_version: str = "preprocessing-1.0"
    cutoff_date: date
    config: PreparationConfig
    input_rows: int
    ignored_future_rows: int
    normalized_sales: list[NormalizedSale]
    daily: list[PreparedDay]
    events: list[CustomerEventAssessment]
