"""Определение типов колонок.

Сервер должен справиться с незнакомым файлом, поэтому тип колонки
определяется по её значениям. Имя колонки учитывается в одном случае:
оно отличает код (год, почтовый индекс, номер заказа) от показателя.
Каждой колонке назначается роль:

* ``date``: дата;
* ``number``: число, по которому можно считать суммы и средние;
* ``category``: текст с небольшим числом повторяющихся значений;
* ``id``: идентификатор строки или код, в расчётах не участвует;
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
DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%d-%m-%Y",
                "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S")
# Дату через косую черту читают двумя способами: в России первым стоит
# день, в США месяц («11/8/2016» там 8 ноября). Порядок выбирает read_dates.
DAY_FIRST = "%d/%m/%Y"
MONTH_FIRST = "%m/%d/%Y"
ORDER_NAMES = {DAY_FIRST: "день/месяц/год", MONTH_FIRST: "месяц/день/год"}
ID_NAME = re.compile(
    r"(^|[\s_])(id|code|index|код|индекс|номер|артикул)($|[\s_])"
    r"|zip|postal|№", re.IGNORECASE)
YEAR_NAME = re.compile(r"(^|[\s_])(year|год)($|[\s_])", re.IGNORECASE)
# Значения колонки «Год» лежат в этих границах. У показателя с таким словом
# в имени («Продажи за год») значения другие.
YEAR_RANGE = (1900, 2100)
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


def to_date(text: pd.Series, slash_format: str = DAY_FIRST) -> pd.Series:
    """Читает даты: сначала формат ISO, потом русские «день.месяц.год».

    Args:
        text: значения колонки текстом.
        slash_format: как читать запись через косую черту: DAY_FIRST
            или MONTH_FIRST.
    """
    result = pd.to_datetime(text, format="ISO8601", errors="coerce")
    for date_format in DATE_FORMATS + (slash_format,):
        missing = result.isna() & text.notna()
        if not missing.any():
            break
        result = result.fillna(pd.to_datetime(text[missing],
                                              format=date_format,
                                              errors="coerce"))
    return result


def read_dates(name: str, text: pd.Series) -> tuple[pd.Series, str, str]:
    """Читает даты и выбирает порядок дня и месяца в записи «1/2/2024».

    Колонка читается целиком в одном порядке: в том, который подошёл
    большему числу значений. Если оба порядка подошли одинаково (все дни
    не больше 12), остаётся «день/месяц/год», и выбор подтверждает
    пользователь.

    Returns:
        Даты, пометка о выбранном порядке и вопрос пользователю. Пометка
        пустая, когда оба порядка дали одни и те же даты. Вопрос пустой,
        когда порядок определился по значениям.
    """
    day_first = to_date(text)
    month_first = to_date(text, MONTH_FIRST)
    if day_first.equals(month_first):
        return day_first, "", ""
    counts = {DAY_FIRST: int(day_first.notna().sum()),
              MONTH_FIRST: int(month_first.notna().sum())}
    if counts[MONTH_FIRST] > counts[DAY_FIRST]:
        dates, chosen, other = month_first, MONTH_FIRST, DAY_FIRST
    else:
        dates, chosen, other = day_first, DAY_FIRST, MONTH_FIRST
    note = (f"даты в колонке «{name}» прочитал в порядке "
            f"{ORDER_NAMES[chosen]}: порядок {ORDER_NAMES[other]} подходит "
            f"для {counts[other]} значений из {int(text.notna().sum())}")
    if counts[chosen] > counts[other]:
        return dates, note, ""
    example = (day_first != month_first) & day_first.notna()
    question = (
        f"Даты в колонке «{name}» читаются двумя способами: "
        f"{ORDER_NAMES[DAY_FIRST]} и {ORDER_NAMES[MONTH_FIRST]}. Выбрал "
        f"{ORDER_NAMES[DAY_FIRST]}: «{text[example].iloc[0]}» прочитано как "
        f"{dates[example].iloc[0].date()}, период получился с "
        f"{dates.min().date()} по {dates.max().date()}. Спросите "
        "пользователя, какой порядок верный. Если первым стоит месяц, даты "
        "в файле нужно записать в виде ГГГГ-ММ-ДД и загрузить файл заново.")
    return dates, note, question


def is_code(name: str, numbers: pd.Series) -> bool:
    """Узнаёт по имени колонку-код: год, почтовый индекс, номер заказа.

    Сумма и среднее по кодам смысла не имеют, поэтому числом такая колонка
    не считается. Код состоит из целых чисел, а год ещё и лежит в границах
    YEAR_RANGE.
    """
    values = numbers.dropna()
    if not (values % 1 == 0).all():
        return False
    if YEAR_NAME.search(name):
        return bool(values.between(*YEAR_RANGE).all())
    return bool(ID_NAME.search(name))


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


def infer_column(name: str,
                 series: pd.Series) -> tuple[pd.Series, str, str, str]:
    """Определяет роль колонки и приводит значения к нужному типу.

    Returns:
        Колонка с приведёнными значениями, её роль, пометка о том, что
        пришлось сделать при чтении, и вопрос пользователю. Пометка и
        вопрос пустые, если сказать нечего.
    """
    text = as_text(series)
    filled = text.dropna()
    if filled.empty:
        return text, EMPTY, "", ""

    numbers = to_number(text)
    is_number = numbers.notna().sum() >= MIN_SHARE * len(filled)
    if is_number and not is_code(name, numbers):
        note = reading_note(name, series, numbers, "числа")
        return numbers, NUMBER, note, ""

    # Код остаётся текстом и получает роль по общим правилам ниже. Даты
    # в нём не ищем: «2023» читается как 1 января 2023 года.
    if not is_number:
        dates, order_note, question = read_dates(name, text)
        if dates.notna().sum() >= MIN_SHARE * len(filled):
            lost_note = reading_note(name, series, dates, "даты")
            note = "; ".join(filter(None, [order_note, lost_note]))
            return dates, DATE, note, question

    unique = filled.nunique()
    if ID_NAME.search(name) and unique == len(filled):
        return text, ID, "", ""
    # Почти пустая колонка (например, редкие комментарии) это не категория.
    if len(filled) < 0.1 * len(series):
        return text, TEXT, "", ""
    if unique <= MAX_CATEGORIES and unique <= max(2, len(filled) // 2):
        return text, CATEGORY, "", ""
    return text, TEXT, "", ""


def infer_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str],
                                            list[str], list[str]]:
    """Определяет роли всех колонок таблицы.

    Returns:
        Таблица с приведёнными значениями, роли колонок, пометки о чтении
        и вопросы пользователю.
    """
    columns, roles, notes, questions = {}, {}, [], []
    for name in raw.columns:
        columns[name], roles[name], note, question = infer_column(
            name, raw[name])
        if note:
            notes.append(note)
        if question:
            questions.append(question)
    return pd.DataFrame(columns, index=raw.index), roles, notes, questions


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
