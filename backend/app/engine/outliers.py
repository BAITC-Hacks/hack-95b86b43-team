"""Document-level and anonymous-client project-sale candidates for one SKU/scope."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
from statistics import median


@dataclass(frozen=True)
class Sale:
    day: date
    document: str
    quantity: D
    product: str
    warehouse: str
    client_id: str | None = None


@dataclass(frozen=True)
class OutlierCandidate:
    id: str
    documents: tuple[str, ...]
    first_day: date
    last_day: date
    quantity: D
    threshold: D
    reason: str


@dataclass(frozen=True)
class OutlierResult:
    candidates: tuple[OutlierCandidate, ...]
    protected_documents: tuple[str, ...]
    limitations: tuple[str, ...]


def detect_outliers(sales: tuple[Sale, ...], as_of: date, absolute_minimum: D,
                    client_window_days: int = 7, minimum_observations: int = 8) -> OutlierResult:
    if not isinstance(absolute_minimum, D) or not absolute_minimum.is_finite() or absolute_minimum < 0:
        raise ValueError("An explicit finite nonnegative absolute threshold is required")
    if type(client_window_days) is not int or client_window_days < 1 or type(minimum_observations) is not int or minimum_observations < 3:
        raise ValueError("Invalid detection window/minimum observations")
    past = [s for s in sales if s.day < as_of]
    if len({(s.product, s.warehouse) for s in past}) > 1:
        raise ValueError("Outlier detection requires one product and warehouse scope")
    documents = {}
    for sale in past:
        if not isinstance(sale.quantity, D) or not sale.quantity.is_finite() or sale.quantity < 0:
            raise ValueError("Provide normalized nonnegative sales; returns require separate semantics")
        if not sale.document:
            raise ValueError("Document identifier is required")
        if sale.document in documents:
            previous = documents[sale.document]
            if (sale.day, sale.client_id) != (previous.day, previous.client_id):
                raise ValueError("Conflicting date/client for the same document")
            documents[sale.document] = Sale(sale.day, sale.document, previous.quantity + sale.quantity,
                                            sale.product, sale.warehouse, sale.client_id)
        else:
            documents[sale.document] = sale
    ordered = sorted(documents.values(), key=lambda s: (s.day, s.document))
    quantities = [s.quantity for s in ordered if s.quantity > 0]
    limitations = []
    if any(s.client_id is None for s in ordered):
        limitations.append("Client analysis unavailable for documents without anonymous client_id")
    if len(quantities) < minimum_observations:
        return OutlierResult((), (), tuple(limitations + ["Insufficient document observations for outlier detection"]))
    center = median(quantities)
    mad = median(abs(q - center) for q in quantities)
    threshold = max(absolute_minimum, center * 6, center + D("1.4826") * mad * 6)
    # Bounded, non-transitive bundles: a chain of small purchases cannot create an unlimited window.
    clients = defaultdict(list)
    bundles = []
    for sale in ordered:
        if sale.client_id is None:
            bundles.append([sale])
        else:
            clients[sale.client_id].append(sale)
    for events in clients.values():
        group = []
        for sale in events:
            if group and (sale.day - group[0].day).days >= client_window_days:
                bundles.append(group)
                group = []
            group.append(sale)
        if group:
            bundles.append(group)
    high = [bundle for bundle in bundles if sum(s.quantity for s in bundle) >= threshold
            and sum(s.quantity for s in bundle) > center]
    protected, candidates = set(), []
    recent = ordered[-5:]
    sustained = len(recent) == 5 and (recent[-1].day - recent[0].day).days >= 14 and sum(s.quantity >= threshold for s in recent) >= 3
    for bundle in high:
        client = bundle[0].client_id
        comparable = [b for b in high if (client is not None and b[0].client_id == client)
                      or (client is None and b[0].client_id is None)]
        recurring_months = {(b[0].day.year, b[0].day.month) for b in comparable}
        recurrent = len(recurring_months) >= 3 and (client is not None or len(comparable) >= len(bundles) / 10)
        recent_group = sustained and all(s.day >= recent[0].day for s in bundle)
        if recurrent or recent_group:
            protected.update(s.document for s in bundle)
            continue
        ids = tuple(sorted(s.document for s in bundle))
        evidence = [(s.document, s.day.isoformat(), str(s.quantity), s.client_id) for s in sorted(bundle, key=lambda s: s.document)]
        key = sha256(json.dumps([bundle[0].product, bundle[0].warehouse, evidence], ensure_ascii=False).encode()).hexdigest()
        candidates.append(OutlierCandidate(key, ids, bundle[0].day, bundle[-1].day,
            sum(s.quantity for s in bundle), threshold,
            "client_window_above_robust_threshold" if len(bundle) > 1 else "document_above_robust_threshold"))
    return OutlierResult(tuple(sorted(candidates, key=lambda c: (c.first_day, c.id))),
                         tuple(sorted(protected)), tuple(limitations))


def cleaned_daily(sales: tuple[Sale, ...], start: date, as_of: date, detection: OutlierResult,
                  confirmed_ids: frozenset[str], *, coverage_complete: bool):
    """Zero-fill only an explicitly complete transaction coverage; remove confirmed candidates only."""
    if coverage_complete is not True or start >= as_of:
        raise ValueError("Explicit complete date coverage is required for daily aggregation")
    available = {candidate.id for candidate in detection.candidates}
    if not confirmed_ids.issubset(available):
        raise ValueError("Unknown or no longer eligible outlier confirmation")
    excluded = {doc for c in detection.candidates if c.id in confirmed_ids for doc in c.documents}
    daily = {start + timedelta(days=i): D(0) for i in range((as_of - start).days)}
    excluded_quantity = D(0)
    for sale in sales:
        if start <= sale.day < as_of:
            if sale.document in excluded:
                excluded_quantity += sale.quantity
            else:
                daily[sale.day] += sale.quantity
    return daily, excluded_quantity
