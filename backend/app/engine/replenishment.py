import math
from typing import Dict, Any

def calculate_sku_replenishment(
    forecast_demand: float,
    safety_stock: float,
    free_stock: float,
    in_transit: float,
    moq: float = 1.0,
    multiplicity: float = 1.0,
    lead_time_days: int = 14,
    days_to_stockout: float = None
) -> Dict[str, Any]:
    """
    Рассчитывает потребность в закупке H = L + R с применением MOQ и кратности.
    """
    # 1. Расчёт чистой потребности
    total_coverage_needed = forecast_demand + safety_stock
    current_assets = free_stock + in_transit
    raw_need = max(0.0, total_coverage_needed - current_assets)

    # 2. Округление и применение ограничений
    if raw_need <= 0:
        recommended_qty = 0.0
    else:
        # Применяем MOQ
        target_qty = max(raw_need, moq)
        # Округляем вверх до ближайшей кратности
        if multiplicity > 1.0:
            recommended_qty = math.ceil(target_qty / multiplicity) * multiplicity
        else:
            recommended_qty = math.ceil(target_qty)

    # 3. Определение срочности (риск дефицита раньше, чем приедет заказ)
    is_urgent = False
    if days_to_stockout is not None and days_to_stockout < lead_time_days:
        is_urgent = True

    return {
        "raw_need": round(raw_need, 2),
        "recommended_qty": round(recommended_qty, 2),
        "is_urgent": is_urgent,
        "parameters": {
            "forecast_demand": round(forecast_demand, 2),
            "safety_stock": round(safety_stock, 2),
            "free_stock": round(free_stock, 2),
            "in_transit": round(in_transit, 2),
            "moq": moq,
            "multiplicity": multiplicity,
            "lead_time_days": lead_time_days
        }
    }
