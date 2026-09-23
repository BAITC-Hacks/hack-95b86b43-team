"""Behavioral checks for procurement decisions, without synthetic ground truth."""

import json
from datetime import date, timedelta
from decimal import Decimal
from math import exp, log

import pytest

from backend.app.engine.contracts import (
    DatasetContext, Inbound, InputDataset, Inventory, Product, ProductSupplier, Supplier,
)
from backend.app.engine.forecast import fit_forecasts
from backend.app.engine.preprocessing.models import CustomerEventAssessment, PreparedDay, PreparedSales, PreparationConfig
from backend.app.engine.replenishment import calculate_recommendations, round_order


def case(*, quantity=10, stock=200, lead=14, days=84, start=date(2026, 1, 1), moq="0", multiple="1"):
    as_of = start + timedelta(days=days)
    source = {"source_file": "fixture.csv", "source_row": 2}
    product = Product(**source, sku="00123", name="Cable", category_id="CAT", base_unit="m", active_from=start)
    dataset = InputDataset(
        context=DatasetContext(as_of_date=as_of, history_start=start, history_end=as_of - timedelta(days=1)),
        products=[product], suppliers=[Supplier(**source, supplier_id="SUP", supplier_name="Supplier")],
        product_suppliers=[ProductSupplier(**source, sku="00123", supplier_id="SUP", is_primary=True,
                                          lead_time_days=lead, moq=moq, order_multiple=multiple)],
        inventory=[Inventory(**source, sku="00123", warehouse_id="WH", snapshot_date=as_of,
                             on_hand=Decimal(str(stock)), reserved="0", blocked="0")],
    )
    daily = []
    for index in range(days):
        day = start + timedelta(days=index)
        qty = Decimal(str(quantity(day, index) if callable(quantity) else quantity))
        daily.append(PreparedDay(date=day, sku="00123", warehouse_id="WH", gross_sales_qty=max(Decimal(0), qty),
                                 net_sales_qty=qty, availability=1, observed_sales=qty,
                                 estimated_demand=max(Decimal(0), qty), demand_for_baseline=qty,
                                 demand_status="AVAILABLE", estimation_method="observed"))
    prepared = PreparedSales(cutoff_date=as_of - timedelta(days=1), config=PreparationConfig(),
                             input_rows=days, ignored_future_rows=0, normalized_sales=[], daily=daily, events=[])
    return dataset, prepared


def shipment(dataset, offset, ordered="60", received="0", status="confirmed", name="PO"):
    dataset.inbound.append(Inbound(source_file="inbound.csv", source_row=2, po_line_id=name, sku="00123",
                                  warehouse_id="WH", supplier_id="SUP", qty_ordered=ordered, qty_received=received,
                                  eta=dataset.context.as_of_date + timedelta(days=offset), status=status))


def recommendation(dataset, prepared, **kwargs):
    return calculate_recommendations(dataset, prepared, **kwargs)["recommendations"][0]


def test_manual_example_order_is_90_and_explanation_balances():
    dataset, prepared = case(quantity=13.2, stock=200, multiple="10")
    shipment(dataset, 7)
    row = recommendation(dataset, prepared)
    assert row["recommended_qty"] == 90
    assert row["forecast_demand"] == pytest.approx(277.2)
    assert row["safety_stock"] == 66
    assert row["raw_requirement"] == pytest.approx(83.2)
    assert row["rounding_adjustment"] == pytest.approx(6.8)
    assert sum(step["value"] for step in row["explanation_steps"]) == pytest.approx(90)
    assert all(point["lost_with_order"] == 0 for point in row["projection"])
    assert row["projection"][-1]["stock_with_order"] >= row["safety_stock"]


def test_reservations_and_blocked_stock_reduce_availability():
    dataset, prepared = case(stock=300)
    original = recommendation(dataset, prepared)
    dataset.inventory[0] = dataset.inventory[0].model_copy(update={"reserved": Decimal(80), "blocked": Decimal(20)})
    row = recommendation(dataset, prepared)
    assert row["available_stock"] == 200
    assert row["recommended_qty"] > original["recommended_qty"]


def test_partial_receipts_only_count_remaining_quantity():
    dataset, prepared = case()
    shipment(dataset, 3, ordered="100", received="40")
    row = recommendation(dataset, prepared)
    assert row["inbound_qty"] == 60
    assert row["recommended_qty"] == 0


def test_late_cancelled_received_and_overdue_receipts_do_not_hide_need():
    dataset, prepared = case()
    expected = recommendation(dataset, prepared)["recommended_qty"]
    shipment(dataset, 21, ordered="1000", name="AFTER")  # End-exclusive horizon.
    shipment(dataset, 3, ordered="1000", status="cancelled", name="CANCELLED")
    shipment(dataset, 3, ordered="1000", status="received", name="DONE")
    shipment(dataset, -1, ordered="1000", name="OVERDUE")
    row = recommendation(dataset, prepared)
    assert row["recommended_qty"] == expected
    assert row["inbound_qty"] == 0
    assert any("Просроченных" in warning for warning in row["data_warnings"])


def test_lost_sales_before_arrival_are_not_ordered_as_backlog():
    dataset, prepared = case(stock=0, lead=14)
    row = recommendation(dataset, prepared)
    assert row["urgency"] == "critical"
    assert row["unmet_demand_before_arrival"] == 140
    assert row["raw_requirement"] == 120  # 7 future days + 5 safety days, not 26 days.
    assert row["shortage_date"] == dataset.context.as_of_date.isoformat()
    assert sum(point["lost_with_order"] for point in row["projection"]) == 140
    assert row["projection"][14]["new_order"] == 120


def test_late_large_receipt_requires_bridging_order_despite_positive_final_balance():
    dataset, prepared = case(stock=0, lead=2)
    shipment(dataset, 6, ordered="1000")
    row = recommendation(dataset, prepared, review_days=7, safety_days=0)
    assert row["balance_requirement"] == 0
    assert row["raw_requirement"] == 40  # Four days from new arrival until existing arrival.
    assert row["recommended_qty"] == 40
    assert all(point["lost_with_order"] == 0 for point in row["projection"][2:])


def test_zero_demand_does_not_trigger_moq():
    dataset, prepared = case(quantity=0, stock=0, moq="100", multiple="20")
    row = recommendation(dataset, prepared)
    assert row["recommended_qty"] == row["forecast_demand"] == 0
    assert row["urgency"] == "none"


def test_decimal_order_rounding_and_moq():
    assert round_order(0, Decimal(100), Decimal("0.25")) == 0
    assert round_order(1.01, Decimal("1.2"), Decimal("0.25")) == Decimal("1.25")
    assert round_order(10.00000000001, Decimal(0), Decimal(1)) == 10


def test_micro_pack_precision_is_preserved_in_recommendation_contract():
    dataset, prepared = case(quantity=0.000001, stock=0, lead=0, multiple="0.000003")
    row = recommendation(dataset, prepared, safety_days=0)
    assert row["recommended_qty"] == 0.000009
    assert row["order_multiple"] == 0.000003
    assert Decimal(row["recommended_qty_exact"]) % Decimal(row["order_multiple_exact"]) == 0


@pytest.mark.parametrize("quantity", [0.1, 0.2, 1.1, 13.2, 0.000001])
def test_exact_fractional_coverage_does_not_create_phantom_pack(quantity):
    dataset, prepared = case(quantity=quantity, stock=quantity * 26)
    row = recommendation(dataset, prepared, use_trend=False)
    assert row["recommended_qty"] == row["raw_requirement"] == 0


def test_stockout_switch_changes_actual_prediction_upwards():
    dataset, prepared = case(stock=0)
    for index in range(70, 84):
        prepared.daily[index] = prepared.daily[index].model_copy(update={
            "availability": 0, "gross_sales_qty": Decimal(0), "net_sales_qty": Decimal(0),
            "observed_sales": Decimal(0), "estimated_demand": Decimal(10),
            "demand_for_baseline": Decimal(10), "demand_status": "STOCKOUT"})
    corrected = recommendation(dataset, prepared, use_trend=False)
    naive = recommendation(dataset, prepared, use_stockout=False, use_trend=False)
    assert corrected["forecast_demand"] > naive["forecast_demand"]
    assert corrected["stockout_days"] == 14
    assert corrected["estimated_lost_demand"] == 140
    assert corrected["base_daily_demand"] == 10


def test_outlier_switch_changes_actual_prediction_without_destroying_raw_chart():
    dataset, prepared = case(stock=0)
    day = prepared.daily[-10]
    prepared.daily[-10] = day.model_copy(update={"observed_sales": Decimal(1010),
                                               "excluded_sales_qty": Decimal(1000),
                                               "is_excluded_from_baseline": True})
    corrected = recommendation(dataset, prepared, use_trend=False)
    naive = recommendation(dataset, prepared, use_outliers=False, use_trend=False)
    assert corrected["forecast_demand"] < naive["forecast_demand"]
    assert corrected["excluded_qty"] == 1000
    assert corrected["chart"][-1]["observed"] == naive["chart"][-1]["observed"]
    assert sum(point["baseline"] for point in corrected["chart"]) < sum(point["baseline"] for point in naive["chart"])


def test_seasonal_profile_uses_future_month_and_is_normalized():
    dataset, prepared = case(start=date(2024, 9, 1), days=730,
                             quantity=lambda day, _: 20 if day.month in {6, 7, 8} else 10)
    forecast = fit_forecasts(dataset, prepared)["00123", "WH"]
    assert forecast.seasonality_source == "sku"
    assert sum(forecast.seasonality) / 12 == pytest.approx(1)
    assert forecast.seasonality[6] > forecast.seasonality[0] * 1.8
    assert forecast.demand(date(2026, 7, 1), date(2026, 7, 1)) > forecast.demand(date(2026, 9, 1), date(2026, 9, 1))
    assert forecast.growth_pct == pytest.approx(0)


def test_category_shape_is_scale_independent_and_short_sku_uses_fallback():
    dataset, prepared = case(start=date(2024, 9, 1), days=730,
                             quantity=lambda day, _: 20 if day.month in {6, 7, 8} else 10)
    other = dataset.products[0].model_copy(update={"sku": "NEW", "base_unit": "pcs", "active_from": date(2026, 8, 20)})
    dataset.products.append(other)
    dataset.inventory.append(dataset.inventory[0].model_copy(update={"sku": "NEW"}))
    prepared.daily.extend(day.model_copy(update={"sku": "NEW", "observed_sales": Decimal(1000),
                                                 "demand_for_baseline": Decimal(1000)})
                          for day in list(prepared.daily)[-12:])
    forecasts = fit_forecasts(dataset, prepared)
    assert forecasts["NEW", "WH"].seasonality_source == "category"
    assert forecasts["NEW", "WH"].seasonality == pytest.approx(forecasts["00123", "WH"].seasonality)
    assert forecasts["NEW", "WH"].base_daily_demand > forecasts["00123", "WH"].base_daily_demand * 20


def test_steady_growth_detected_capped_and_switchable():
    dataset, prepared = case(quantity=lambda _day, i: 10 * exp(log(1.5) * i / 30))
    growing = recommendation(dataset, prepared)
    flat = recommendation(dataset, prepared, use_trend=False)
    assert growing["growth_pct"] == pytest.approx(30)
    assert flat["growth_pct"] == 0
    assert growing["forecast_demand"] > flat["forecast_demand"]


def test_declining_trend_is_capped_and_non_negative():
    dataset, prepared = case(quantity=lambda _day, i: 100 * exp(log(0.5) * i / 30))
    row = recommendation(dataset, prepared)
    assert row["growth_pct"] == pytest.approx(-20)
    assert all(point["demand"] >= 0 for point in row["projection"])


def test_slow_sustained_growth_uses_monthly_history_when_weekly_change_is_small():
    dataset, prepared = case(start=date(2024, 9, 1), days=730,
                             quantity=lambda _day, index: 10 * exp(log(1.015) * index / 30))
    row = recommendation(dataset, prepared)
    assert row["trend_source"] == "monthly_history"
    assert row["growth_pct"] == pytest.approx(1.5, abs=0.1)


def test_negative_net_returns_do_not_generate_negative_forecast():
    dataset, prepared = case(quantity=-10, stock=0, moq="20")
    row = recommendation(dataset, prepared)
    assert row["forecast_demand"] == row["recommended_qty"] == 0


def test_future_prepared_days_cannot_change_decision():
    dataset, prepared = case()
    before = calculate_recommendations(dataset, prepared)
    future = prepared.daily[-1].model_copy(update={"date": dataset.context.as_of_date,
                                                 "observed_sales": Decimal(1000000),
                                                 "demand_for_baseline": Decimal(1000000)})
    prepared.daily.append(future)
    assert calculate_recommendations(dataset, prepared) == before


def test_stale_preprocessing_is_rejected_instead_of_mixed_with_current_inventory():
    dataset, prepared = case()
    prepared.cutoff_date -= timedelta(days=1)
    with pytest.raises(ValueError, match="cutoff"):
        calculate_recommendations(dataset, prepared)


def test_warehouse_and_category_filters_and_json_output_are_deterministic():
    dataset, prepared = case()
    first = calculate_recommendations(dataset, prepared, warehouse_id="WH", category_id="CAT")
    assert len(first["recommendations"]) == 1
    assert json.dumps(first, sort_keys=True) == json.dumps(calculate_recommendations(dataset, prepared), sort_keys=True)
    assert calculate_recommendations(dataset, prepared, warehouse_id="OTHER")["recommendations"] == []


@pytest.mark.parametrize("kwargs", [{"review_days": 0}, {"review_days": 91}, {"safety_days": -1}, {"safety_days": True}])
def test_invalid_policy_is_rejected(kwargs):
    dataset, prepared = case()
    with pytest.raises(ValueError):
        calculate_recommendations(dataset, prepared, **kwargs)


def test_more_stock_cannot_increase_order_and_higher_safety_cannot_reduce_it():
    dataset, prepared = case(stock=180)
    original = recommendation(dataset, prepared)
    assert recommendation(dataset, prepared, safety_days=10)["recommended_qty"] >= original["recommended_qty"]
    dataset.inventory[0] = dataset.inventory[0].model_copy(update={"on_hand": Decimal(250)})
    assert recommendation(dataset, prepared)["recommended_qty"] <= original["recommended_qty"]


def test_new_item_without_evidence_uses_same_unit_peer_and_requires_review():
    dataset, prepared = case(stock=10000)
    dataset.products.append(dataset.products[0].model_copy(update={"sku": "NEW", "active_from": dataset.context.as_of_date}))
    dataset.inventory.append(dataset.inventory[0].model_copy(update={"sku": "NEW"}))
    dataset.product_suppliers.append(dataset.product_suppliers[0].model_copy(update={"sku": "NEW"}))
    row = next(row for row in calculate_recommendations(dataset, prepared)["recommendations"] if row["sku"] == "NEW")
    assert row["forecast_source"] == "category_same_unit"
    assert row["base_daily_demand"] == 10
    assert row["urgency"] == "review"


@pytest.mark.parametrize("code,excluded,expected", [
    ("excluded_large_customer_event", True, "Разовый крупный заказ исключён"),
    ("excluded_large_customer_event_continuation", True, "Раздробленный разовый заказ"),
    ("retained_recurring_large_customer", False, "Регулярная крупная закупка сохранена"),
    ("large_event_insufficient_history_review", False, "истории недостаточно"),
    ("large_event_uncertain_review", False, "разовый характер не подтверждён"),
])
def test_customer_event_explanations_match_detection_and_scenario(code, excluded, expected):
    dataset, prepared = case()
    prepared.events = [CustomerEventAssessment(
        event_id="SPLIT", date=prepared.cutoff_date, start_date=prepared.cutoff_date - timedelta(days=2),
        sku="00123", warehouse_id="WH", customer_anon_id="ANON", order_ids=["PROJECT"],
        sale_line_ids=["PART-1", "PART-2"], actual_qty=Decimal(600), current_day_qty=Decimal(200),
        typical_qty=Decimal(10), threshold_qty=Decimal(80), exclusion_threshold_qty=Decimal(100),
        large_event_score=Decimal(20), relative_to_daily_demand=Decimal(60), history_days=60,
        customer_previous_orders=0, customer_mean_qty=Decimal(0), customer_median_qty=Decimal(0),
        customer_max_qty=Decimal(0), is_large_customer_event=True, is_outlier=excluded,
        is_excluded_from_baseline=excluded, large_event_reason=code,
    )]
    event = recommendation(dataset, prepared)["events"][0]
    assert expected in event["reason"]
    assert event["reason_code"] == code
    assert event["excluded"] is excluded
    scenario = recommendation(dataset, prepared, use_outliers=False)["events"][0]
    assert scenario["excluded"] is False
    if excluded:
        assert "сохранён в этом сценарии" in scenario["reason"]
        assert "исключение выбросов отключено" in scenario["reason"]
    else:
        assert scenario["reason"] == event["reason"]
