"""Lossless scalar parsing. Unknown is never implicitly converted to zero."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

MONTHS = {name: i + 1 for i, name in enumerate(
    ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"))}


def label(value: object) -> str:
    return " ".join(str(value).split()).casefold() if value is not None else ""


def identifier(value: object) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    # Numeric Excel identifiers cannot be restored safely without a format rule.
    if not isinstance(value, str):
        raise ValueError("Identifier must be stored as text; numeric code needs review")
    return value.strip()


def number(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a quantity")
    try:
        result = Decimal(str(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric value") from exc
    if not result.is_finite():
        raise ValueError("Non-finite numeric value")
    return result


def month(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([а-я]+)\.?\s+(20\d{2})(?:\s+г\.)?", label(value))
    if not match:
        return None
    prefix = match[1][:3]
    if prefix == "мая":
        prefix = "май"
    return date(int(match[2]), MONTHS[prefix], 1) if prefix in MONTHS else None


def timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            pass
    raise ValueError("Invalid transaction date")
