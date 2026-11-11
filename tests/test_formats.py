"""Незнакомые файлы: другой разделитель, кодировка, заголовок не сверху."""

import pandas as pd

from analytics_mcp import columns
from helpers import Session, run


def test_numbers_written_as_text():
    """Числа читаются из русской и английской записи."""
    text = pd.Series(["12 450,50", "1,234.56", "1.234,56", "95 ₽", "7",
                      "15%", "нет"], dtype="string")
    assert columns.to_number(text).tolist()[:6] == [
        12450.5, 1234.56, 1234.56, 95.0, 7.0, 15.0]
    assert pd.isna(columns.to_number(text).iloc[6])


def test_dates_in_iso_and_russian_format():
    """Даты читаются в формате ISO и «день.месяц.год»."""
    text = pd.Series(["2024-03-05", "05.03.2024", "2024-03-05 00:00:00",
                      "5 марта"], dtype="string")
    dates = columns.to_date(text)
    assert dates.iloc[:3].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-03-05"] * 3
    assert pd.isna(dates.iloc[3])


def test_russian_csv_with_semicolons_and_cp1251(tmp_path):
    """CSV из русского Excel: «;», Windows-1251, запятая в дробях."""
    path = tmp_path / "выгрузка.csv"
    rows = ["Дата;Город;Выручка", "05.03.2024;Казань;12 450,50",
            "06.03.2024;Москва;9 800,00", "07.03.2024;Казань;11 020,10",
            "08.03.2024;Москва;10 500,00"]
    path.write_bytes("\n".join(rows).encode("cp1251"))

    async def scenario(session: Session) -> None:
        reply = (await session.call("load_data", file_path=str(path))).data
        assert reply["notes"][0] == "разделитель «;», кодировка Windows-1251"
        roles = {c["name"]: c["role"] for c in reply["columns"]}
        assert roles == {"Дата": "date", "Город": "category",
                         "Выручка": "number"}
        stats = (await session.call(
            "describe_data", dataset_id=reply["dataset_id"])).data
        assert stats["numbers"]["Выручка"]["sum"] == 43770.6
        assert stats["dates"]["Дата"]["first"] == "2024-03-05"

    run(tmp_path, scenario)


def test_dirty_excel_with_title_above_header(tmp_path):
    """Excel-выгрузка: заголовок в третьей строке, числа и даты текстом."""
    async def scenario(session: Session) -> None:
        reply = (await session.call("load_data",
                                    file_path="orders_dirty.xlsx")).data
        notes = " ".join(reply["notes"])
        assert "заголовок таблицы нашёл в строке 3" in notes
        assert "пропустил пустые строки: 2" in notes
        assert "были записаны текстом" in notes
        roles = {c["name"]: c["role"] for c in reply["columns"]}
        assert roles["Дата заказа"] == "date"
        assert roles["Выручка, руб"] == "number"
        assert roles["Категория"] == "category"

        cleaned = (await session.call(
            "clean_data", dataset_id=reply["dataset_id"])).data
        actions = " ".join(cleaned["actions"])
        assert "привёл к одному написанию" in actions
        assert "удалил полные дубликаты строк: 4" in actions
        assert cleaned["outliers"][0]["gross_examples"] == [1250000]

    run(tmp_path, scenario)


def test_table_pasted_into_chat(tmp_path):
    """Таблицу можно передать текстом, без файла на сервере."""
    async def scenario(session: Session) -> None:
        reply = (await session.call(
            "load_data",
            csv_text="month,sales\n2024-01-01,10\n2024-02-01,20")).data
        assert reply["source"] == "текст из чата"
        assert reply["rows"] == 2

    run(tmp_path, scenario)
