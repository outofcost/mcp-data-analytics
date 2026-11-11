"""Правила очистки на маленьких таблицах, где ответ виден глазами."""

import pandas as pd

from analytics_mcp import columns
from analytics_mcp.skills.cleaning import find_outliers, normalize_text


def test_gross_outlier_is_excluded_and_doubtful_value_stays():
    """Грубый выброс исключается, значение у границы ждёт человека."""
    # Обычные значения от 100 до 200: квартили 125 и 175, размах 50.
    values = list(range(100, 205, 5)) + [400, 5000]
    frame = pd.DataFrame({"amount": [float(v) for v in values]})
    mask, found = find_outliers(frame, {"amount": columns.NUMBER})
    # 400 лежит в 4,5 размаха от квартиля: подозрительно, но в расчёте.
    assert found[0]["to_check_examples"] == [400.0]
    # 5000 лежит дальше 6 размахов: грубый выброс, из расчёта исключён.
    assert found[0]["gross_examples"] == [5000.0]
    assert frame.loc[mask, "amount"].tolist() == [5000.0]


def test_category_spelling_is_unified_to_most_frequent():
    """Разное написание одной категории сводится к самому частому."""
    frame = pd.DataFrame({"city": pd.Series(
        ["Казань", "казань", "Казань", "Москва", "МОСКВА", "москва",
         "москва"], dtype="string")})
    actions = normalize_text(frame, {"city": columns.CATEGORY})
    assert frame["city"].tolist() == ["Казань"] * 3 + ["москва"] * 4
    assert "3 строк" in actions[0]
