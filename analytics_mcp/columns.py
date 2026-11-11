"""Определение типов колонок.

Сервер должен справиться с незнакомым файлом, поэтому тип колонки
определяется по её значениям, без опоры на имена. Каждой колонке
назначается роль:

* ``date``: дата;
* ``number``: число, по которому можно считать суммы и средние;
* ``category``: текст с небольшим числом повторяющихся значений;
* ``id``: идентификатор строки, в расчётах не участвует;
* ``text``: прочий текст;
* ``empty``: колонка без значений.
"""

import re

import pandas as pd

DATE = "date"
NUMBER = "number"
CATEGORY = "category"
ID = "id"
TEXT = "text"
EMPTY = "empty"
# Служебная колонка, которую добавляет очистка: признак выброса.
FLAG = "flag"
OUTLIER_COLUMN = "is_outlier"

# Колонка получает роль, если ей соответствует такая доля непустых значений.
MIN_SHARE = 0.9
MAX_CATEGORIES = 20

EMPTY_MARKS = {"", "-", "—", "н/д", "нд", "нет данных", "n/a", "na", "nan",
               "null", "none", "nat"}
DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y",
                "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S")
ID_NAME = re.compile(r"(^|[\s_])(id|код|номер|артикул)($|[\s_])|№",
                     re.IGNORECASE)
# Слова в имени колонки, по которым выбирается главный показатель.
MEASURE_WORDS = ("sales", "revenue", "amount", "выруч", "продаж", "сумм",
                 "оборот")
PROFIT_WORDS = ("profit", "margin", "прибыл", "марж")


def as_text(series: pd.Series) -> pd.Series:
    """Приводит колонку к тексту, пустые отметки заменяет на пропуск."""
    text = series.astype("string").str.strip()
    return text.mask(text.str.lower().isin(EMPTY_MARKS))


def to_number(text: pd.Series) -> pd.Series:
    """Читает числа, записанные текстом: «12 450,50», «1,234.56», «95 ₽»."""
    cleaned = text.str.replace(r"[\s  ]", "", regex=True)
    cleaned = cleaned.str.replace(r"(руб\.?|р\.|₽|\$|€|%)$", "", regex=True)
    both = cleaned.str.contains(",", na=False) & cleaned.str.contains(
        ".", na=False, regex=False)
    comma_last = cleaned.str.rfind(",") > cleaned.str.rfind(".")
    # «1.234,56»: точка делит тысячи. «1,234.56»: тысячи делит запятая.
    cleaned = cleaned.mask(both & comma_last,
                           cleaned.str.replace(".", "", regex=False))
    cleaned = cleaned.mask(both & ~comma_last,
                           cleaned.str.replace(",", "", regex=False))
    cleaned = cleaned.str.replace(",", ".", regex=False)
    # float64 вместо Int64: в колонке могут появиться дробные значения
    # (например, медиана при заполнении пропусков).
    return pd.to_numeric(cleaned, errors="coerce").astype("float64")


def to_date(text: pd.Series) -> pd.Series:
    """Читает даты: сначала формат ISO, потом русские «день.месяц.год»."""
    result = pd.to_datetime(text, format="ISO8601", errors="coerce")
    for date_format in DATE_FORMATS:
        missing = result.isna() & text.notna()
        if not missing.any():
            break
        result = result.fillna(pd.to_datetime(text[missing],
                                              format=date_format,
                                              errors="coerce"))
    return result


def reading_note(name: str, series: pd.Series, parsed: pd.Series,
                 kind: str) -> str:
    """Сообщает, что пришлось сделать, чтобы прочитать колонку."""
    notes = []
    as_string = series.map(lambda value: isinstance(value, str))
    # В Excel часть значений колонки бывает записана текстом: «12 450,50».
    if as_string.any() and not as_string[series.notna()].all():
        notes.append(f"в колонке «{name}» {int(as_string.sum())} значений "
                     f"были записаны текстом, прочитал их как {kind}")
    lost = int(as_text(series).notna().sum() - parsed.notna().sum())
    if lost:
        notes.append(f"в колонке «{name}» {lost} значений прочитать как "
                     f"{kind} не удалось, заменил их пропусками")
    return "; ".join(notes)


def infer_column(name: str, series: pd.Series) -> tuple[pd.Series, str, str]:
    """Определяет роль колонки и приводит значения к нужному типу.

    Returns:
        Колонка с приведёнными значениями, её роль и пометка о том, что
        пришлось сделать при чтении (пустая строка, если ничего).
    """
    text = as_text(series)
    filled = text.dropna()
    if filled.empty:
        return text, EMPTY, ""

    numbers = to_number(text)
    if numbers.notna().sum() >= MIN_SHARE * len(filled):
        note = reading_note(name, series, numbers, "числа")
        if (ID_NAME.search(name) and numbers.dropna().is_unique
                and len(filled) > 1):
            return numbers, ID, note
        return numbers, NUMBER, note

    dates = to_date(text)
    if dates.notna().sum() >= MIN_SHARE * len(filled):
        return dates, DATE, reading_note(name, series, dates, "даты")

    unique = filled.nunique()
    if ID_NAME.search(name) and unique == len(filled):
        return text, ID, ""
    # Почти пустая колонка (например, редкие комментарии) это не категория.
    if len(filled) < 0.1 * len(series):
        return text, TEXT, ""
    if unique <= MAX_CATEGORIES and unique <= max(2, len(filled) // 2):
        return text, CATEGORY, ""
    return text, TEXT, ""


def infer_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str],
                                            list[str]]:
    """Определяет роли всех колонок таблицы."""
    columns, roles, notes = {}, {}, []
    for name in raw.columns:
        columns[name], roles[name], note = infer_column(name, raw[name])
        if note:
            notes.append(note)
    return pd.DataFrame(columns, index=raw.index), roles, notes


def columns_with_role(roles: dict[str, str], role: str) -> list[str]:
    """Возвращает имена колонок с заданной ролью в порядке таблицы."""
    return [name for name, value in roles.items() if value == role]


def has_word(name: str, words: tuple[str, ...]) -> bool:
    """Проверяет, есть ли в имени колонки одно из слов."""
    return any(word in name.lower() for word in words)


def pick_measure(roles: dict[str, str]) -> str | None:
    """Выбирает главный числовой показатель таблицы.

    Сначала ищет колонку, похожую по имени на выручку или продажи. Если
    такой нет, берёт первую числовую колонку.
    """
    numbers = columns_with_role(roles, NUMBER)
    for name in numbers:
        if has_word(name, MEASURE_WORDS):
            return name
    return numbers[0] if numbers else None


def pick_profit(roles: dict[str, str]) -> str | None:
    """Находит колонку с прибылью, если она есть."""
    for name in columns_with_role(roles, NUMBER):
        if has_word(name, PROFIT_WORDS):
            return name
    return None
