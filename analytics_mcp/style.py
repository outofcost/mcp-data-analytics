"""Оформление графиков: одна палитра и одни правила для всех.

Правила: заголовок слева, подписи осей с единицами, русские подписи,
без верхней и правой рамки, один акцентный цвет.
"""

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # рисуем в файл, окно не нужно

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

GREEN = "#2DBE64"
MID_GREEN = "#198E48"
DARK_GREEN = "#055A31"
TEXT = "#1A1A1A"
GREY = "#75767D"
LIGHT_GREY = "#E3E3E8"
# Цвета линий, когда на графике несколько рядов.
SERIES_COLORS = [GREEN, DARK_GREEN, GREY, "#8FD9AB", "#4A4A4E"]
# Для корреляций: серый для отрицательных, зелёный для положительных.
CORRELATION_MAP = LinearSegmentedColormap.from_list(
    "correlation", [GREY, "#FFFFFF", MID_GREEN])

FIGURE_SIZE = (8, 4.5)
DPI = 110

MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
          "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_FULL = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
               "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

# Подписи для колонок из задания: название и единица измерения.
# Для незнакомой колонки подписью служит её имя. Валюты здесь нет: по имени
# Sales не узнать, рубли в файле или доллары. Валюта попадает на ось, только
# если она написана в имени колонки («Выручка, руб»).
KNOWN_COLUMNS = {
    "date": ("Дата", ""),
    "product": ("Товар", ""),
    "region": ("Регион", ""),
    "sales": ("Продажи", ""),
    "quantity": ("Количество", "шт."),
    "profit": ("Прибыль", ""),
}


# Единицы, которые сервер узнаёт в конце имени колонки: «Выручка, руб».
UNITS = {"руб": "руб.", "руб.": "руб.", "р": "руб.", "р.": "руб.", "₽": "₽",
         "шт": "шт.", "шт.": "шт.", "кг": "кг", "%": "%"}
# Дательный падеж для заголовков «Продажи по товарам». Для колонки, которой
# здесь нет, заголовок получается «Продажи по колонке «Склад»».
GROUPED_BY = {
    "товар": "товарам", "регион": "регионам", "категория": "категориям",
    "город": "городам", "канал": "каналам", "клиент": "клиентам",
    "магазин": "магазинам", "менеджер": "менеджерам",
}


def split_unit(name: str) -> tuple[str, str]:
    """Делит имя колонки на название и единицу измерения.

    «Sales» даёт («Продажи», «»), «Выручка, руб» даёт («Выручка», «руб.»).
    У незнакомой колонки без единицы названием служит её имя.
    """
    known = KNOWN_COLUMNS.get(name.strip().lower())
    if known:
        return known
    title, comma, unit = name.rpartition(",")
    if comma and unit.strip().lower() in UNITS:
        return title.strip(), UNITS[unit.strip().lower()]
    return name.strip(), ""


def column_title(name: str) -> str:
    """Возвращает название колонки для заголовка графика, без единицы."""
    return split_unit(name)[0]


def column_label(name: str, scale_word: str = "") -> str:
    """Возвращает подпись оси для колонки: «Выручка, тыс. руб.»."""
    title, unit = split_unit(name)
    suffix = " ".join(part for part in (scale_word, unit) if part)
    return f"{title}, {suffix}" if suffix else title


def by_column(name: str) -> str:
    """Возвращает конец заголовка графика: «по товарам»."""
    title = column_title(name)
    if title.lower() in GROUPED_BY:
        return f"по {GROUPED_BY[title.lower()]}"
    return f"по колонке «{title}»"


def plural(count: int, one: str, few: str, many: str) -> str:
    """Выбирает форму слова после числа: 1 строка, 2 строки, 5 строк."""
    tail, tens = count % 10, count % 100
    if tail == 1 and tens != 11:
        return one
    if 2 <= tail <= 4 and not 12 <= tens <= 14:
        return few
    return many


def pick_scale(max_value: float) -> tuple[float, str]:
    """Подбирает масштаб оси: тысячи или миллионы для больших чисел."""
    if abs(max_value) >= 1_000_000:
        return 1_000_000, "млн"
    if abs(max_value) >= 10_000:
        return 1_000, "тыс."
    return 1, ""


def format_number(value: float, exact: bool = False) -> str:
    """Пишет число по-русски: пробел между тысячами, запятая в дроби.

    Большие числа округляются до целых, у малых остаётся до двух знаков
    после запятой без лишних нулей. С exact=True большое число тоже
    сохраняет дробную часть: так пишется значение, которое сервер подставил
    в данные.
    """
    if abs(value) >= 100 and not exact:
        text = f"{value:,.0f}"
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def new_figure(title: str) -> tuple[Figure, plt.Axes]:
    """Создаёт график с общим оформлением."""
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    axes.set_title(title, loc="left", fontsize=13, color=TEXT, pad=12)
    axes.spines[["top", "right"]].set_visible(False)
    axes.spines[["left", "bottom"]].set_color(GREY)
    axes.tick_params(colors=TEXT, labelsize=9)
    axes.grid(axis="y", color=LIGHT_GREY, linewidth=0.8)
    axes.set_axisbelow(True)
    return figure, axes


def save_figure(figure: Figure, path: Path) -> bytes:
    """Сохраняет график в PNG и возвращает его байты."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight",
                   facecolor="white")
    plt.close(figure)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return buffer.getvalue()
