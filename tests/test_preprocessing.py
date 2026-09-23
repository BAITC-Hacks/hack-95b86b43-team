from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend.app.engine.contracts import DatasetContext, InputDataset, Inventory, Product, Sale, Stockout
from backend.app.engine.preprocessing.aggregation import aggregate_daily_sales, normalize_sales
from backend.app.engine.preprocessing.models import PreparationConfig
from backend.app.engine.preprocessing.report import generate_preprocessing_report
from backend.app.engine.preprocessing.sales_cleaning import prepare_sales
from backend.app.engine.stockouts import stockout_calendar


START = date(2026, 1, 1)


def sale(index, qty="10", customer="CUST-A", sku="00123", operation="sale", order="auto", line=None):
    return Sale(source_file="sales.csv", source_row=2 + index, sale_line_id=line or f"S-{index}-{customer}-{operation}",
        date=START + timedelta(days=index), sku=sku, warehouse_id="WH-1", customer_anon_id=customer,
        qty=str(qty), unit_price="12.50", operation_type=operation,
        order_id=f"O-{index}-{customer}" if order == "auto" else order)


def outage(first, stop, sku="00123"):
    return Stockout(source_file="stockouts.csv", source_row=2, sku=sku, warehouse_id="WH-1",
        start_date=START + timedelta(days=first), end_date_exclusive=START + timedelta(days=stop))


def dataset(sales=None, intervals=None, days=100, peer_unit=None, active=0):
    end = START + timedelta(days=days - 1)
    products = [Product(source_file="products.csv", source_row=2, sku="00123", name="Demo",
                        category_id="CAT-1", base_unit="m", active_from=START + timedelta(days=active))]
    if peer_unit:
        products.append(Product(source_file="products.csv", source_row=3, sku="OTHER", name="Peer",
                                category_id="CAT-1", base_unit=peer_unit, active_from=START))
    stocks = [Inventory(source_file="inventory.csv", source_row=i+2, snapshot_date=end + timedelta(days=1),
                        sku=p.sku, warehouse_id="WH-1", on_hand="10", reserved="0", blocked="0")
              for i, p in enumerate(products)]
    return InputDataset(context=DatasetContext(as_of_date=end + timedelta(days=1), history_start=START, history_end=end),
                        products=products, inventory=stocks, sales=sales or [], stockouts=intervals or [])


def daily(prepared, index, sku="00123"):
    return next(d for d in prepared.daily if d.date == START + timedelta(days=index) and d.sku == sku)


def test_sale_return_and_aggregation():
    source = dataset([sale(0, "10.25", line="1"), sale(0, "3.50", operation="return", line="2"),
                      sale(0, "4", customer="CUST-B", line="3")])
    normalized = normalize_sales(source.sales, source.context.history_end)
    assert [r.signed_qty for r in normalized] == [Decimal("10.25"), Decimal("-3.50"), Decimal("4")]
    d = next(iter(aggregate_daily_sales(normalized).values()))
    assert d.gross_sales_qty == Decimal("14.25")
    assert d.return_qty == Decimal("3.50")
    assert d.net_sales_qty == Decimal("10.75")
    assert d.transaction_count == 3 and d.unique_customers == 2
    assert d.max_single_customer_qty == Decimal("10.25")
    prepared = prepare_sales(source)
    assert daily(prepared, 0).demand_for_baseline == Decimal("10.75")
    assert "return_adjusted" in daily(prepared, 0).reasons
    assert daily(prepared, 0).sku == "00123"


def test_negative_returns_preserved_without_negative_estimate():
    p = prepare_sales(dataset([sale(0, "3", operation="return")]))
    assert daily(p, 0).net_sales_qty == -3
    assert daily(p, 0).demand_for_baseline == -3
    assert daily(p, 0).estimated_demand == 0


def test_stockout_intervals_and_imputation():
    source = dataset([sale(i) for i in range(28)], [outage(28, 33)], days=34)
    mask = stockout_calendar(source.stockouts, START, source.context.history_end)
    assert len(mask) == 5
    p = prepare_sales(source)
    for i in range(28, 33):
        d = daily(p, i)
        assert d.availability == 0 and d.observed_sales == 0
        assert d.demand_for_baseline == d.estimated_demand == 10
        assert d.estimation_method == "weekday_28d"
        assert d.latest_donor_date < d.date
        assert d.estimation_sample_count == 4  # Estimates are never reused as observations.
    assert daily(p, 33).availability == 1 and daily(p, 33).demand_for_baseline == 0


@pytest.mark.parametrize("past,method,qty", [(0, "zero_history", 0), (2, "recent_28d", 10)])
def test_short_history_fallback(past, method, qty):
    p = prepare_sales(dataset([sale(i) for i in range(past)], [outage(past, past+1)], days=past+1))
    d = daily(p, past)
    assert d.estimation_method == method and d.demand_for_baseline == qty
    assert d.insufficient_history


@pytest.mark.parametrize("unit,method,qty", [("m", "category_fallback", 20), ("pcs", "zero_history", 0)])
def test_category_fallback_respects_units(unit, method, qty):
    source = dataset([sale(i, "20", sku="OTHER") for i in range(7)], [outage(7, 8)],
                     days=8, peer_unit=unit, active=7)
    d = daily(prepare_sales(source), 7)
    assert d.estimation_method == method
    assert d.demand_for_baseline == qty
    assert d.insufficient_history


def test_long_outage_does_not_reuse_own_estimates():
    p = prepare_sales(dataset([sale(i) for i in range(7)], [outage(7, 110)], days=110))
    assert daily(p, 7).estimated_demand == 10
    assert daily(p, 109).estimation_method == "zero_history"
    assert daily(p, 109).estimated_demand == 0


def test_available_zeros_are_part_of_baseline():
    p = prepare_sales(dataset([sale(0)], [outage(28, 29)], days=29))
    assert len(p.daily) == 29
    assert daily(p, 28).estimated_demand == Decimal(30) / 28  # Zeros lower the rate and cap weekday spikes.
    assert daily(p, 28).estimation_sample_count == 4


def test_large_one_off_excludes_only_its_rows():
    source = dataset([sale(i) for i in range(40)] + [sale(35, "900", customer="BIG", line="BIG-1")])
    before = source.model_dump_json()
    p = prepare_sales(source)
    event = next(e for e in p.events if e.customer_anon_id == "BIG")
    assert event.is_large_customer_event and event.is_excluded_from_baseline
    assert event.large_event_score > 0
    assert event.large_event_reason == "excluded_large_customer_event"
    assert daily(p, 35).gross_sales_qty == 910
    assert daily(p, 35).excluded_sales_qty == 900
    assert daily(p, 35).demand_for_baseline == 10
    assert len(p.normalized_sales) == len(source.sales)
    assert source.model_dump_json() == before


def test_large_sale_at_large_scale_is_normal():
    source = dataset([sale(i, "500") for i in range(35)] + [sale(35, "700", customer="BIG")])
    p = prepare_sales(source)
    assert not p.events[-1].is_large_customer_event
    assert daily(p, 35).demand_for_baseline == 700


def test_recurring_large_customer_is_retained():
    source = dataset([sale(i) for i in range(100)] + [sale(i, qty, customer="BIG", line=f"BIG-{i}")
                     for i, qty in ((5, "800"), (35, "850"), (65, "790"), (95, "830"))])
    p = prepare_sales(source)
    events = [e for e in p.events if e.customer_anon_id == "BIG"]
    assert all(not e.is_excluded_from_baseline for e in events)
    assert events[0].large_event_reason == "large_event_insufficient_history_review"
    assert all(e.large_event_reason == "retained_recurring_large_customer" for e in events[1:])
    assert daily(p, 65).demand_for_baseline == 800


def test_recurring_customer_can_be_recognized_after_initial_exclusion():
    source = dataset([sale(i) for i in range(100)] + [sale(i, qty, customer="NEW-BIG", line=f"BIG-{i}")
                     for i, qty in ((35, "900"), (65, "850"), (95, "910"))])
    at_first_order = prepare_sales(source, START + timedelta(days=35))
    complete = prepare_sales(source)
    events = [e for e in complete.events if e.customer_anon_id == "NEW-BIG"]
    assert events[0].is_excluded_from_baseline
    assert all(not event.is_excluded_from_baseline for event in events[1:])
    assert events[1].large_event_reason == "retained_recurring_large_customer"
    assert daily(complete, 65).demand_for_baseline == 860
    # New evidence affects later decisions only: an honest historical replay
    # cannot discover the recurrence before the second purchase has happened.
    assert daily(complete, 35) == daily(at_first_order, 35)
    assert events[0] == next(e for e in at_first_order.events if e.customer_anon_id == "NEW-BIG")


@pytest.mark.parametrize("order", [None, "SPLIT"])
def test_split_orders_are_causal_and_window_bounded(order):
    source = dataset([sale(i) for i in range(50)] + [sale(i, "300", customer="BIG", order=order, line=f"BIG-{i}")
                     for i in (35, 36, 37, 45)])
    p = prepare_sales(source)
    events = [e for e in p.events if e.customer_anon_id == "BIG"]
    assert len({e.event_id for e in events[:3]}) == 1
    assert events[0].actual_qty == 300 and events[2].actual_qty == 900
    assert events[3].event_id != events[2].event_id
    assert events[0].sale_line_ids == ["BIG-35"]


def test_same_day_different_order_ids_are_combined():
    p = prepare_sales(dataset([sale(i) for i in range(35)] + [sale(35, "300", customer="BIG", line=f"PART-{i}", order=f"O-{i}") for i in range(3)]))
    event = next(e for e in p.events if e.customer_anon_id == "BIG")
    assert event.actual_qty == 900 and len(event.order_ids) == 3
    assert event.is_excluded_from_baseline


def test_later_split_part_never_rewrites_earlier_day():
    source = dataset([sale(i) for i in range(35)] + [sale(i, qty, customer="BIG", order="SPLIT")
                     for i, qty in ((35, "35"), (36, "35"), (37, "300"))])
    short = prepare_sales(source, START + timedelta(days=35))
    full = prepare_sales(source)
    assert daily(short, 35) == daily(full, 35)
    assert daily(full, 35).demand_for_baseline == 35
    assert daily(full, 37).demand_for_baseline == 0


def test_outlier_not_used_to_impute_following_stockout():
    source = dataset([sale(i) for i in range(35)] + [sale(35, "900", customer="BIG")], [outage(36, 41)])
    p = prepare_sales(source)
    assert daily(p, 36).estimated_demand == 10


def test_stockout_sales_conflict_is_quarantined():
    source = dataset([sale(i) for i in range(35)] + [sale(35, "900", customer="BIG")], [outage(35, 36)])
    p = prepare_sales(source)
    d = daily(p, 35)
    assert d.demand_status == "STOCKOUT_SALES_CONFLICT"
    assert d.is_large_customer_event
    assert d.observed_sales == 900 and d.estimated_demand is None
    assert d.demand_for_baseline is None
    assert generate_preprocessing_report(p)["stockout_sales_conflicts"] == 1


def test_return_during_stockout_and_linked_project_return():
    source = dataset([sale(i) for i in range(35)] + [sale(35, "900", customer="BIG", order="PROJECT"),
                     sale(36, "100", customer="BIG", operation="return", order="PROJECT"),
                     sale(37, "3", operation="return")], [outage(36, 38)])
    p = prepare_sales(source)
    assert daily(p, 36).return_qty == daily(p, 36).excluded_return_qty == 100
    assert daily(p, 36).estimated_demand == 10
    assert daily(p, 37).estimated_demand == 7


def test_duplicates_preserved_but_counted_once():
    first = sale(0)
    duplicate = first.model_copy(update={"source_row": 20})
    p = prepare_sales(dataset([first, duplicate]))
    assert len(p.normalized_sales) == 2
    assert sum(r.is_technical_duplicate for r in p.normalized_sales) == 1
    assert daily(p, 0).transaction_count == 1 and daily(p, 0).net_sales_qty == 10


def test_conflicting_duplicate_rejected():
    first = sale(0)
    other = first.model_copy(update={"qty": Decimal("20")})
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        prepare_sales(dataset([first, other]))


def test_no_future_leakage_or_mutation():
    source = dataset([sale(i) for i in range(75)] + [sale(35, "900", customer="BIG", line="BIG"),
                     sale(80, "900000", customer="FUTURE")], [outage(40, 45)])
    prefix = prepare_sales(source, START + timedelta(days=44))
    full = prepare_sales(source)
    assert prefix.daily == [d for d in full.daily if d.date <= prefix.cutoff_date]
    assert prefix.events == [e for e in full.events if e.date <= prefix.cutoff_date]
    assert prefix.normalized_sales == [r for r in full.normalized_sales if r.original.date <= prefix.cutoff_date]
    assert prefix.ignored_future_rows > 0
    assert prefix.model_dump_json() == prepare_sales(source, prefix.cutoff_date).model_dump_json()


def test_new_product_does_not_get_prelaunch_zero_history():
    p = prepare_sales(dataset([sale(40)], days=45, active=40))
    assert len(p.daily) == 5
    assert p.daily[0].date == START + timedelta(days=40)


def test_config_and_cutoff_validation():
    with pytest.raises(ValueError):
        PreparationConfig(split_window_days=30)
    with pytest.raises(ValueError):
        prepare_sales(dataset(), START - timedelta(days=1))


def test_customer_with_normal_large_history_can_have_one_off():
    records = [sale(i) for i in range(60)]
    records += [sale(i, q, customer="BIG", line=f"BIG-{i}")
                for i, q in ((5, "100"), (10, "120"), (15, "95"), (20, "110"), (40, "900"))]
    p = prepare_sales(dataset(records))
    event = next(e for e in p.events if e.customer_anon_id == "BIG" and e.date == START + timedelta(days=40))
    assert event.customer_previous_orders == 4
    assert event.customer_max_qty == 120
    assert event.is_excluded_from_baseline


def test_today_peer_sales_cannot_change_today_stockout():
    records = [sale(i, "20", sku="OTHER") for i in range(7)]
    base = dataset(records, [outage(7, 8)], days=8, peer_unit="m", active=7)
    first = prepare_sales(base)
    changed = base.model_copy(update={"sales": records + [sale(7, "900000", sku="OTHER")]})
    assert daily(first, 7) == daily(prepare_sales(changed), 7)
