import numpy as np
import pandas as pd
from typing import Tuple, List

def detect_outliers_mad(sales_series: pd.Series, threshold: float = 3.5) -> Tuple[pd.Series, List[int]]:
    """
    Детектирует разовые крупнооптовые заказы с использованием Robust Z-Score (MAD).
    Возвращает очищенный ряд и индексы найденных выбросов.
    """
    if len(sales_series) < 3 or sales_series.sum() == 0:
        return sales_series.copy(), []

    median = sales_series.median()
    mad = (sales_series - median).abs().median()

    if mad == 0:
        # Резервное правило на основе средненалогового отклонения
        mean_abs_dev = (sales_series - median).abs().mean()
        if mean_abs_dev == 0:
            return sales_series.copy(), []
        modified_z_scores = 0.6745 * (sales_series - median) / mean_abs_dev
    else:
        modified_z_scores = 0.6745 * (sales_series - median) / mad

    outlier_mask = modified_z_scores > threshold
    cleaned_series = sales_series.copy()

    # Заменяем выбросы медианным значением устойчивого спроса
    cleaned_series[outlier_mask] = median
    outlier_indices = sales_series[outlier_mask].index.tolist()

    return cleaned_series, outlier_indices
