"""Чужие файлы: американские даты, шапка с реквизитами, итоги, коды."""

import pandas as pd

from analytics_mcp import columns
from helpers import Session, run


def roles_of(reply: dict) -> dict[str, str]:
    """Собирает роли колонок из ответа load_data."""
    return {c["name"]: c["role"] for c in reply["columns"]}


def test_month_first_dates_keep_every_row(tmp_path):
    """Даты «месяц/день/год» читаются без перестановки и без потерь.

    Порядок «день/месяц» подходит девяти строкам из десяти: раньше сервер
    выбирал его, менял в них день с месяцем, а десятую строку очистка
    удаляла как строку без даты.
    """
    days = (3, 4, 5, 6, 7, 8, 9, 10, 11, 25)
    path = tmp_path / "us_dates.csv"
    path.write_text("Date,Sales\n" + "\n".join(
        f"01/{day:02d}/2024,{100 + day}" for day in days), encoding="utf-8")

    async def scenario(session: Session) -> None:
        reply = (await session.call("load_data", file_path=str(path))).data
        assert roles_of(reply)["Date"] == "date"
        assert ("даты в колонке «Date» прочитал в порядке месяц/день/год: "
                "порядок день/месяц/год подходит для 9 значений из 10"
                ) in reply["notes"]
        assert reply["questions"] == []
        stats = (await session.call(
            "describe_data", dataset_id=reply["dataset_id"])).data
        assert stats["dates"]["Date"] == {
            "first": "2024-01-03", "last": "2024-01-25", "days": 22}
        cleaned = (await session.call(
            "clean_data", dataset_id=reply["dataset_id"])).data
        assert cleaned["rows_after"] == 10

    run(tmp_path, scenario)


def test_ambiguous_dates_go_to_questions(tmp_path):
    """Если подходят оба порядка, сервер называет выбранный в questions."""
    async def scenario(session: Session) -> None:
        reply = (await session.call(
            "load_data",
            csv_text="Date,Sales\n01/03/2024,10\n02/03/2024,20\n"
                     "05/04/2024,30")).data
        assert roles_of(reply)["Date"] == "date"
        assert reply["preview"][0]["Date"] == "2024-03-01"
        assert len(reply["questions"]) == 1
        question = reply["questions"][0]
        assert "день/месяц/год и месяц/день/год" in question
        assert "«01/03/2024» прочитано как 2024-03-01" in question
        assert "с 2024-03-01 по 2024-04-05" in question

        clear = (await session.call(
            "load_data",
            csv_text="Date,Sales\n2024-03-01,10\n2024-03-02,20")).data
        assert clear["questions"] == []

    run(tmp_path, scenario)


def test_requisites_above_header_and_total_row(tmp_path):
    """Строка реквизитов не становится заголовком, «Итого» не считается."""
    rows = [
        ["Отчёт о продажах", None, None, None],
        ["Сформирован: 01.02.2024", None, None, "Валюта: руб."],
        ["Дата", "Магазин", "Выручка", "Чеков"],
        ["2024-01-01", "Север", 10, 1],
        ["2024-01-02", "Юг", 20, 2],
        ["2024-01-03", "Север", 30, 3],
        ["Итого", None, 60, 6],
    ]
    path = tmp_path / "report.xlsx"
    pd.DataFrame(rows).to_excel(path, header=False, index=False)

    async def scenario(session: Session) -> None:
        reply = (await session.call("load_data", file_path=str(path))).data
        assert roles_of(reply) == {"Дата": "date", "Магазин": "category",
                                   "Выручка": "number", "Чеков": "number"}
        assert reply["rows"] == 3
        notes = " ".join(reply["notes"])
        assert "заголовок таблицы нашёл в строке 3" in notes
        assert "убрал строки итогов" in notes
        assert "или «Total»): 1" in notes
        stats = (await session.call(
            "describe_data", dataset_id=reply["dataset_id"])).data
        assert stats["numbers"]["Выручка"]["sum"] == 60

    run(tmp_path, scenario)


def test_total_row_is_dropped_without_date_column(tmp_path):
    """Строка «Всего» убирается и в таблице без дат."""
    async def scenario(session: Session) -> None:
        reply = (await session.call(
            "load_data",
            csv_text="Отдел,Сумма\nA,10\nB,20\nA,30\nB,40\nВСЕГО:,100")).data
        assert reply["rows"] == 4
        stats = (await session.call(
            "describe_data", dataset_id=reply["dataset_id"])).data
        assert stats["numbers"]["Сумма"]["sum"] == 100

    run(tmp_path, scenario)


def test_broken_xlsx_says_what_to_do(tmp_path):
    """Файл .xlsx, который не книга Excel, даёт ошибку с советом."""
    path = tmp_path / "fake.xlsx"
    path.write_text("это не эксель", encoding="utf-8")

    async def scenario(session: Session) -> None:
        reply = await session.call("load_data", file_path=str(path))
        assert reply.is_error
        assert "«fake.xlsx» не читается как Excel" in reply.text
        assert "сохраните заново как .xlsx или как CSV" in reply.text

    run(tmp_path, scenario)


def test_codes_are_not_measures(tmp_path):
    """Год, почтовый индекс и номер строки в суммы не попадают."""
    async def scenario(session: Session) -> None:
        reply = (await session.call(
            "load_data",
            csv_text="Row ID,Year,Postal Code,Sales,Discount %\n"
                     "1,2023,101000,10,5\n2,2023,101001,20,0\n"
                     "3,2024,101002,30,10\n4,2024,101003,40,0")).data
        assert roles_of(reply) == {
            "Row ID": "id", "Year": "category", "Postal Code": "id",
            "Sales": "number", "Discount %": "number"}
        stats = (await session.call(
            "describe_data", dataset_id=reply["dataset_id"])).data
        assert list(stats["numbers"]) == ["Sales", "Discount %"]
        assert stats["categories"]["Year"][0]["value"] == "2023"

    run(tmp_path, scenario)


def test_measure_with_code_word_stays_number():
    """Слово «год» или «индекс» в имени ещё не делает колонку кодом."""
    sales = pd.Series([1200.0, 3400.0, 560.0])
    assert not columns.is_code("Продажи за год", sales)
    assert not columns.is_code("Индекс цен", pd.Series([101.3, 99.8]))
    assert columns.is_code("Год", pd.Series([2023.0, 2024.0]))
    assert columns.is_code("ZipCode", pd.Series([101000.0, 101001.0]))


def test_single_value_column_is_not_a_category():
    """Колонка с одним значением на всю таблицу в разрезы не идёт."""
    series = pd.Series(["United States"] * 10, dtype="string")
    assert columns.infer_column("Country", series)[1] == columns.TEXT
