"""Генерирует тестовые данные для аналитического сервера.

Создаёт два файла рядом с собой:

* ``sales_data.csv``: продажи продуктового магазина за 2023–2024 годы
  в рублях, колонки как в задании: Date, Product, Region, Sales, Quantity,
  Profit;
* ``orders_dirty.xlsx``: «грязная» выгрузка с другой структурой: заголовок
  не в первой строке, числа и даты текстом, разное написание категорий.

Зерно генератора фиксировано, повторный запуск даёт те же файлы.

В ``sales_data.csv`` заложены три закономерности. По ним я проверяю, что
отчёт содержит осмысленные выводы (см. ``docs/acceptance.md``):

1. сезонность: в декабре продажи выше, чем в среднем месяце;
2. Казань растёт быстрее остальных регионов;
3. товар «Готовые обеды» продаётся в убыток.

Запуск из корня репозитория: ``python data/generate_data.py``
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

SEED = 20261111
DATA_DIR = Path(__file__).parent

# Товар: (цена за единицу в рублях, типичная выручка одной записи, маржа).
PRODUCTS = {
    "Молоко": (95, 45_000, 0.18),
    "Хлеб": (60, 30_000, 0.25),
    "Сыр": (720, 60_000, 0.22),
    "Яблоки": (140, 35_000, 0.20),
    "Кофе": (890, 55_000, 0.30),
    "Готовые обеды": (350, 50_000, -0.08),  # закономерность 3: убыток
}
# Регион: множитель выручки в начале и в конце периода.
REGIONS = {
    "Москва": (1.40, 1.48),
    "Санкт-Петербург": (1.10, 1.16),
    "Казань": (0.60, 1.60),  # закономерность 2: быстрый рост
    "Новосибирск": (0.80, 0.84),
}
# Закономерность 1: множитель по месяцам, декабрь заметно выше остальных.
SEASON = {1: 0.80, 2: 0.85, 3: 0.95, 4: 1.00, 5: 1.00, 6: 0.95,
          7: 0.90, 8: 0.95, 9: 1.00, 10: 1.05, 11: 1.20, 12: 1.60}
MONTHS = [(year, month) for year in (2023, 2024) for month in range(1, 13)]
ROWS_PER_MONTH = 8


def days_in_month(year: int, month: int) -> int:
    """Возвращает число дней в месяце."""
    first_of_next = date(year + month // 12, month % 12 + 1, 1)
    return (first_of_next - timedelta(days=1)).day


def build_sales(rng: random.Random) -> list[dict]:
    """Строит чистые записи продаж с тремя заложенными закономерностями."""
    product_cycle: list[str] = []
    rows = []
    for index, (year, month) in enumerate(MONTHS):
        progress = index / (len(MONTHS) - 1)
        # В каждом месяце каждый регион встречается одинаковое число раз,
        # товары идут по перемешанному кругу: так закономерности не тонут
        # в случайном составе записей.
        regions = list(REGIONS) * (ROWS_PER_MONTH // len(REGIONS))
        rng.shuffle(regions)
        for region in regions:
            if not product_cycle:
                product_cycle = list(PRODUCTS)
                rng.shuffle(product_cycle)
            product = product_cycle.pop()
            price, typical_sales, margin = PRODUCTS[product]
            start, end = REGIONS[region]
            region_factor = start + (end - start) * progress
            sales = (typical_sales * region_factor * SEASON[month]
                     * rng.uniform(0.9, 1.1))
            quantity = max(1, round(sales / price))
            sales = round(quantity * price * rng.uniform(0.97, 1.03), -1)
            profit = round(sales * (margin + rng.uniform(-0.02, 0.02)))
            day = rng.randint(1, days_in_month(year, month))
            rows.append({
                "Date": date(year, month, day).isoformat(),
                "Product": product,
                "Region": region,
                "Sales": int(sales),
                "Quantity": quantity,
                "Profit": profit,
            })
    rows.sort(key=lambda row: row["Date"])
    return rows


def add_dirt(rows: list[dict], rng: random.Random) -> list[dict]:
    """Добавляет пропуски, дубликаты и выбросы, чтобы было что чистить."""
    rows = [dict(row) for row in rows]
    spoiled = rng.sample(range(len(rows)), 11)
    for index in spoiled[:4]:
        rows[index]["Quantity"] = ""
    for index in spoiled[4:7]:
        rows[index]["Profit"] = ""
    for index in spoiled[7:9]:
        rows[index]["Region"] = ""
    for index in spoiled[9:11]:
        rows[index]["Sales"] *= 10  # опечатка: лишний ноль в выручке
    for index in rng.sample(range(len(rows)), 3):
        rows.insert(index, dict(rows[index]))  # точный дубликат строки
    return rows


def write_sales(path: Path, rng: random.Random) -> int:
    """Пишет sales_data.csv и возвращает число строк."""
    rows = add_dirt(build_sales(rng), rng)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_dirty_orders(path: Path, rng: random.Random) -> int:
    """Пишет orders_dirty.xlsx: незнакомая структура и типичный мусор."""
    categories = {"Молочные продукты": 52_000, "Овощи и фрукты": 41_000,
                  "Бакалея": 33_000, "Готовая еда": 47_000, "Напитки": 28_000}
    cities = {"Москва": 1.5, "Санкт-Петербург": 1.1, "Казань": 0.8}
    channels = {"Магазин": (1.0, 0.9), "Доставка": (0.5, 1.3),
                "Самовывоз": (0.4, 0.5)}

    records = []
    for week in range(52):
        day = date(2024, 1, 1) + timedelta(days=week * 7 + rng.randint(0, 6))
        progress = week / 51
        for _ in range(3):
            category = rng.choice(list(categories))
            city = rng.choice(list(cities))
            channel = rng.choice(list(channels))
            start, end = channels[channel]
            revenue = (categories[category] * cities[city]
                       * (start + (end - start) * progress)
                       * rng.uniform(0.85, 1.15))
            receipts = max(1, round(revenue / rng.uniform(700, 1100)))
            records.append([day, category, city, channel,
                            round(revenue, 2), receipts,
                            rng.choice([0, 0, 5, 10, 15]), None])

    # Мусор, который встречается в настоящих выгрузках.
    for row in rng.sample(records, 30):
        row[0] = row[0].strftime("%d.%m.%Y")            # дата текстом
    for row in rng.sample(records, 22):
        text = f"{row[4]:,.2f}".replace(",", " ").replace(".", ",")
        row[4] = text                                   # «12 450,50» текстом
    for row in rng.sample(records, 14):
        row[1] = rng.choice([row[1].lower(), row[1] + " "])
    for row in rng.sample(records, 9):
        row[2] = row[2].lower()
    for row in rng.sample(records, 5):
        row[5] = None                                   # пропуск в «Чеков»
    for row in rng.sample(records, 3):
        row[2] = None                                   # пропуск в «Город»
    rng.choice(records)[4] = 1_250_000.0                # выброс в выручке
    rng.choice(records)[7] = "уточнить у менеджера"
    for index in rng.sample(range(len(records)), 4):
        records.insert(index, list(records[index]))     # дубликаты

    book = Workbook()
    sheet = book.active
    sheet.title = "Выгрузка"
    sheet.append(["Выгрузка заказов интернет-магазина за 2024 год"])
    sheet.append([])
    sheet.append(["Дата заказа", "Категория", "Город", "Канал",
                  "Выручка, руб", "Чеков", "Скидка, %", "Комментарий"])
    for index, row in enumerate(records):
        if index in (40, 97):
            sheet.append([])                            # пустая строка
        sheet.append(row)
    for cell in sheet["A"]:
        if isinstance(cell.value, date):
            cell.number_format = "DD.MM.YYYY"
    book.save(path)
    return len(records)


def main() -> None:
    """Создаёт оба файла и печатает, сколько строк записано."""
    rng = random.Random(SEED)
    sales_rows = write_sales(DATA_DIR / "sales_data.csv", rng)
    order_rows = write_dirty_orders(DATA_DIR / "orders_dirty.xlsx", rng)
    print(f"sales_data.csv: {sales_rows} строк")
    print(f"orders_dirty.xlsx: {order_rows} строк данных")


if __name__ == "__main__":
    main()
