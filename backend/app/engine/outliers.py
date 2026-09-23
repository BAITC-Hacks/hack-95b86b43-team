"""Online customer-event detection: no reclassification using later purchases."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import median

from backend.app.engine.preprocessing.models import CustomerEventAssessment, NormalizedSale, PreparationConfig
from backend.app.engine.stockouts import Observation, mean, recent_observations


@dataclass
class EventState:
    event_id: str
    start: date
    last: date
    qty: Decimal = Decimal(0)
    order_ids: set[str] = field(default_factory=set)
    line_ids: list[str] = field(default_factory=list)
    excluded: bool = False


class CustomerEventDetector:
    def __init__(self, config: PreparationConfig):
        self.config = config
        self.events: dict[tuple[str, str, str], list[EventState]] = defaultdict(list)
        self.order_lookup: dict[tuple[str, str, str, str], EventState] = {}
        self.excluded_orders: set[tuple[str, str, str, str]] = set()

    def assess(self, records: list[NormalizedSale], day: date, history: list[Observation]) -> CustomerEventAssessment:
        sale = records[0].original
        key = sale.sku, sale.warehouse_id, sale.customer_anon_id
        order_ids = {r.original.order_id for r in records if r.original.order_id}
        states = self.events[key]
        eligible = []
        for order_id in sorted(order_ids):
            state = self.order_lookup.get((*key, order_id))
            if state and (day - state.start).days < self.config.split_window_days:
                eligible.append(state)
        if not order_ids and states and not states[-1].order_ids:
            if (day - states[-1].start).days < self.config.split_window_days:
                eligible.append(states[-1])
        if eligible:
            state = min(eligible, key=lambda s: (s.start, s.event_id))
        else:
            state = EventState(event_id=f"EVENT-{sale.sale_line_id}", start=day, last=day)
            states.append(state)
        # Only disjoint earlier events, as observed then, establish recurrence.
        previous = [s for s in states if s is not state and s.last < state.start
                    and (day - s.last).days <= 180]
        previous_qty = [s.qty for s in previous]
        today_qty = sum((r.original.qty for r in records), Decimal(0))
        state.qty += today_qty
        state.last = day
        state.order_ids.update(order_ids)
        state.line_ids.extend(r.original.sale_line_id for r in records)
        for order_id in order_ids:
            self.order_lookup[(*key, order_id)] = state
        observations = recent_observations(history, day, self.config)
        values = [q for _, q in observations]
        positive = [q for q in values if q > 0]
        typical = median(values) if values else Decimal(0)
        if values:
            ordered = sorted(values)
            trim = len(ordered) // 10
            trimmed = ordered[trim:len(ordered) - trim] if trim else ordered
            typical = max(typical, mean(trimmed))
        center = median(values) if values else Decimal(0)
        mad = median([abs(q - center) for q in values]) if values else Decimal(0)
        span = (day - state.start).days + 1
        p95 = sorted(values)[min(len(values) - 1, int(len(values) * .95))] if values else Decimal(0)
        positive_median = median(positive) if positive else Decimal(0)
        threshold = max(typical * max(self.config.relative_days_threshold, Decimal(3 * span)),
                        (center + self.config.mad_multiplier * Decimal("1.4826") * mad) * span,
                        positive_median * 6, p95 * self.config.tail_multiplier)
        scale = Decimal("1.4826") * mad if mad else max(typical, positive_median)
        score = max(Decimal(0), (state.qty - typical * span) / scale) if scale else Decimal(0)
        large = bool(positive and state.qty > threshold)
        historical_peak = max((q for d, q in history if 0 < (day - d).days <= self.config.max_history_age_days),
                              default=Decimal(0))
        exclusion_threshold = max(threshold, historical_peak * self.config.exclusion_peak_multiplier)
        enough = len(values) >= self.config.min_detection_days and len(positive) >= self.config.min_positive_days
        # An exclusion was a decision with the evidence available on that day,
        # not proof that this customer's future orders can never be regular.
        # A later comparable purchase establishes recurrence even when the
        # first purchase was excluded. Never rewrite the earlier assessment.
        recurrent = any(self.config.split_window_days <= (state.start - s.start).days <= 62
                        and s.qty / 2 <= state.qty <= s.qty * 2 for s in previous)
        reason = "normal_customer_event"
        if state.excluded:
            reason = "excluded_large_customer_event_continuation"
        elif large and recurrent:
            reason = "retained_recurring_large_customer"
        elif large and not enough:
            reason = "large_event_insufficient_history_review"
        elif large and state.qty > exclusion_threshold:
            state.excluded = True
            reason = "excluded_large_customer_event"
        elif large:
            reason = "large_event_uncertain_review"
        if state.excluded:
            for order_id in state.order_ids:
                self.excluded_orders.add((*key, order_id))
        for record in records:
            record.event_id = state.event_id
            record.is_large_customer_event = large or state.excluded
            record.is_outlier = state.excluded
            record.is_excluded_from_baseline = state.excluded
            record.reasons.append(reason)
        return CustomerEventAssessment(event_id=state.event_id, date=day, start_date=state.start,
            sku=sale.sku, warehouse_id=sale.warehouse_id, customer_anon_id=sale.customer_anon_id,
            order_ids=sorted(state.order_ids), sale_line_ids=list(state.line_ids), actual_qty=state.qty,
            current_day_qty=today_qty, typical_qty=typical, threshold_qty=threshold,
            exclusion_threshold_qty=exclusion_threshold, large_event_score=score,
            relative_to_daily_demand=state.qty / typical if typical else None, history_days=len(values),
            customer_previous_orders=len(previous), customer_mean_qty=mean(previous_qty),
            customer_median_qty=median(previous_qty) if previous_qty else Decimal(0),
            customer_max_qty=max(previous_qty, default=Decimal(0)),
            is_large_customer_event=large or state.excluded, is_outlier=state.excluded,
            is_excluded_from_baseline=state.excluded, large_event_reason=reason)


def detect_large_customer_orders(records: list[NormalizedSale], day: date,
                                histories: dict[tuple[str, str], list[Observation]],
                                detector: CustomerEventDetector) -> list[CustomerEventAssessment]:
    groups = defaultdict(list)
    for record in records:
        sale = record.original
        if not record.is_technical_duplicate and sale.operation_type == "sale" and sale.qty > 0:
            groups[sale.sku, sale.warehouse_id, sale.customer_anon_id].append(record)
    return [detector.assess(group, day, histories.get((sku, warehouse), []))
            for (sku, warehouse, _), group in sorted(groups.items())]
