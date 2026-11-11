"""Правила очистки на маленьких таблицах, где ответ виден глазами."""

import pandas as pd

from analytics_mcp import columns
from analytics_mcp.skills.cleaning import find_outliers, normalize_text
from helpers import Session, run


def test_gross_outlier_is_excluded_and_doubtful_value_stays():
    """Грубый выброс исключается, значение у границы ждёт человека."""
    # Обычные значения от 100 до 200: квартили 125 и 175, размах 50.
    values = list(range(100, 205, 5)) + [400, 5000]
    frame = pd.DataFrame({"amount": [float(v) for v in values]})
    mask, tail, found = find_outliers(frame, {"amount": columns.NUMBER})
    # 400 лежит в 4,5 размаха от квартиля: подозрительно, но в расчёте.
    assert found[0]["to_check_examples"] == [400.0]
    # 5000 лежит дальше 6 размахов: грубый выброс, из расчёта исключён.
    assert found[0]["gross_examples"] == [5000.0]
    assert frame.loc[mask, "amount"].tolist() == [5000.0]


def test_long_tail_of_large_orders_is_not_excluded():
    """Много крупных значений это свойство данных, из расчёта они не идут."""
    # 95% заказов от 10 до 100, каждый двадцатый крупный: от 500 до 5 450.
    # За порогом в 6 размахов лежит 5% строк: для ошибки ввода это много.
    small = [10 + (n * 7) % 91 for n in range(1900)]
    large = [500 + 50 * n for n in range(100)]
    frame = pd.DataFrame({"sales": [float(v) for v in small + large]})
    mask, tail, found = find_outliers(frame, {"sales": columns.NUMBER})
    assert not mask.any()
    assert int(tail.sum()) == 100
    assert found[0]["gross_outliers"] == 0
    assert found[0]["long_tail"] == 100
    # Сотни значений на проверку человеку не уходят.
    assert found[0]["to_check"] == 0


def test_values_without_a_gap_are_not_excluded():
    """Редкие значения за порогом остаются, если они идут без разрыва."""
    # Обычные значения от 100 до 200: квартили 125 и 175, размах 50.
    usual = [float(v) for v in range(100, 201)] * 4
    # Лесенка от 4 до 8 размахов выше квартиля: 375, 425, 470, 500, 575.
    ladder = [375.0, 425.0, 470.0, 500.0, 575.0]
    frame = pd.DataFrame({"amount": usual + ladder})
    mask, tail, found = find_outliers(frame, {"amount": columns.NUMBER})
    # За порогом 475 два значения, но до ближайшего соседа (470) меньше
    # трёх размахов: это хвост, ошибка ввода стояла бы особняком.
    assert not mask.any()
    assert frame.loc[tail, "amount"].tolist() == [500.0, 575.0]


def test_category_spelling_is_unified_to_most_frequent():
    """Разное написание одной категории сводится к самому частому."""
    frame = pd.DataFrame({"city": pd.Series(
        ["Казань", "казань", "Казань", "Москва", "МОСКВА", "москва",
         "москва"], dtype="string")})
    actions = normalize_text(frame, {"city": columns.CATEGORY})
    assert frame["city"].tolist() == ["Казань"] * 3 + ["москва"] * 4
    assert "3 строк" in actions[0]


def test_report_names_only_what_was_checked(tmp_path):
    """Отчёт очистки не говорит «не нашёл» про то, что не искал."""
    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        skipped = (await session.call(
            "clean_data", dataset_id=raw_id, drop_duplicates=False,
            fill_missing="none", outliers="none")).data
        # Все шаги отключены: дубликаты и пропуски оставлены и названы.
        assert skipped["actions"] == ["таблица не менялась"]
        assert "Дубликаты оставлены: 3." in skipped["untouched"]

        cleaned = (await session.call("clean_data", dataset_id=raw_id)).data
        # Медиана Quantity равна 210,5: пишется то значение, которым
        # заполнены пропуски, без округления.
        assert ("заполнил пропуски в колонке «Quantity» медианой 210,5: 4"
                in cleaned["actions"])

    run(tmp_path, scenario)


def test_long_tail_stays_in_totals_and_is_reported(tmp_path):
    """Очистка оставляет длинный хвост в итогах и сообщает о нём."""
    small = [10 + (n * 7) % 91 for n in range(1900)]
    large = [500 + 50 * n for n in range(100)]
    frame = pd.DataFrame({
        "Order": [f"A{n}" for n in range(2000)],
        "Sales": small + large,
    })
    path = tmp_path / "long_tail.csv"
    frame.to_csv(path, index=False)

    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path=str(path))).data["dataset_id"]
        cleaned = (await session.call("clean_data", dataset_id=raw_id)).data
        assert cleaned["rows_after"] == 2000
        assert any("«Sales»" in note and "100 (5% строк" in note
                   for note in cleaned["untouched"])
        facts = (await session.call(
            "collect_findings", dataset_id=cleaned["dataset_id"])).data
        assert facts["facts"]["строк_в_расчёте"] == 2000
        assert facts["facts"]["итоги"]["Sales"] == sum(small + large)

        # Явная просьба удалить относится и к хвосту.
        removed = (await session.call(
            "clean_data", dataset_id=raw_id, outliers="remove")).data
        assert removed["rows_after"] == 1900

    run(tmp_path, scenario)
