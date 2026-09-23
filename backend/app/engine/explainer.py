import json
from typing import Dict, Any

def generate_calculation_explanation(calc_result: Dict[str, Any], sku_code: str) -> str:
    """
    Генерирует структурированное текстово-числовое объяснение расчёта.
    """
    params = calc_result["parameters"]

    explanation_tree = {
        "sku": sku_code,
        "summary": (
            f"Рекомендовано к закупке: {calc_result['recommended_qty']} шт. "
            f"(Чистая потребность: {calc_result['raw_need']} шт.)"
        ),
        "steps": [
            {
                "step": 1,
                "title": "Оценка покрытия",
                "formula": "Требуемый запас = Прогноз + Страховой запас",
                "values": f"{params['forecast_demand']} + {params['safety_stock']} = {params['forecast_demand'] + params['safety_stock']}"
            },
            {
                "step": 2,
                "title": "Учёт текущих ресурсов",
                "formula": "Доступно = Свободный остаток + В пути",
                "values": f"{params['free_stock']} + {params['in_transit']} = {params['free_stock'] + params['in_transit']}"
            },
            {
                "step": 3,
                "title": "Корректировка на MOQ и Кратность",
                "formula": "Итог = Ceil(Max(Потребность, MOQ) / Кратность) * Кратность",
                "applied_constraints": {
                    "MOQ": params["moq"],
                    "Multiplicity": params["multiplicity"]
                }
            }
        ],
        "urgency_flag": calc_result["is_urgent"]
    }

    return json.dumps(explanation_tree, ensure_ascii=False, indent=2)
