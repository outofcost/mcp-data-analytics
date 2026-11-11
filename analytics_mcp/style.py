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
# Для незнакомой колонки подписью служит её имя.
KNOWN_COLUMNS = {
    "date": ("Дата", ""),
    "product": ("Товар", ""),
    "region": ("Регион", ""),
    "sales": ("Продажи", "₽"),
    "quantity": ("Количество", "шт."),
    "profit": ("Прибыль", "₽"),
}


def column_title(name: str) -> str:
    """Возвращает название колонки для заголовка графика, без единицы."""
    return KNOWN_COLUMNS.get(name.strip().lower(), (name, ""))[0]


def column_label(name: str, scale_word: str = "") -> str:
    """Возвращает подпись оси для колонки, с единицей и масштабом."""
    title, unit = KNOWN_COLUMNS.get(name.strip().lower(), (name, ""))
    suffix = " ".join(part for part in (scale_word, unit) if part)
    return f"{title}, {suffix}" if suffix else title


def pick_scale(max_value: float) -> tuple[float, str]:
    """Подбирает масштаб оси: тысячи или миллионы для больших чисел."""
    if abs(max_value) >= 1_000_000:
        return 1_000_000, "млн"
    if abs(max_value) >= 10_000:
        return 1_000, "тыс."
    return 1, ""


def format_number(value: float) -> str:
    """Пишет число по-русски: пробел между тысячами, запятая в дроби.

    Большие числа округляются до целых, у малых остаётся до двух знаков
    после запятой без лишних нулей.
    """
    if abs(value) >= 100:
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
