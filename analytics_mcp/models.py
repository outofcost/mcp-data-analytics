"""Формат ответов инструментов.

Из этих моделей SDK строит выходную схему (``outputSchema``) каждого
инструмента: клиент заранее знает, какие поля придут. В каждом ответе есть
``next_step``: подсказка модели, что вызвать дальше.

У инструментов с графиками выходной схемы нет: SDK не строит её для ответа
с картинкой. Они возвращают ``ChartResult`` текстом в формате JSON и
картинку вторым блоком.
"""

from typing import Any

from pydantic import BaseModel, Field

NEXT_STEP = "Что вызвать дальше. Выполняйте, пока анализ не завершён"
DATASET_ID = "Идентификатор таблицы. Передавайте его в остальные инструменты"


class ColumnInfo(BaseModel):
    """Одна колонка загруженной таблицы."""

    name: str
    role: str = Field(description="date, number, category, id, text "
                                  "или empty")
    missing: int = Field(description="Сколько пропусков")
    unique: int = Field(description="Сколько разных значений")
    examples: list[str] = Field(description="До трёх примеров значений")


class LoadResult(BaseModel):
    """Ответ load_data: структура загруженной таблицы."""

    dataset_id: str = Field(description=DATASET_ID)
    source: str = Field(description="Имя файла или «текст из чата»")
    rows: int
    columns: list[ColumnInfo]
    duplicates: int = Field(description="Полностью повторяющиеся строки")
    missing_total: int = Field(description="Пропуски во всех колонках")
    notes: list[str] = Field(description="Что сервер сделал при чтении")
    questions: list[str] = Field(
        description="Что стоит уточнить у пользователя до анализа. "
                    "Пустой список: уточнять нечего")
    preview: list[dict[str, str]] = Field(description="Первые три строки")
    next_step: str = Field(description=NEXT_STEP)


class DescribeResult(BaseModel):
    """Ответ describe_data: базовая статистика."""

    dataset_id: str = Field(description=DATASET_ID)
    rows: int
    numbers: dict[str, dict[str, float]] = Field(
        description="По числовым колонкам: count, sum, mean, median, min, "
                    "max, std")
    categories: dict[str, list[dict[str, Any]]] = Field(
        description="По категориям: до пяти частых значений с числом строк "
                    "и долей в процентах")
    dates: dict[str, dict[str, Any]] = Field(
        description="По датам: первая, последняя, число дней между ними")
    missing: dict[str, int] = Field(description="Пропуски по колонкам")
    next_step: str = Field(description=NEXT_STEP)


class CleanResult(BaseModel):
    """Ответ clean_data: что именно сделала очистка."""

    dataset_id: str = Field(
        description="Идентификатор очищенной таблицы. Дальше работайте "
                    "с ним. Исходная таблица не изменилась")
    rows_before: int
    rows_after: int
    actions: list[str] = Field(
        description="Что сделано, с числами: сколько строк удалено, "
                    "сколько пропусков заполнено и чем")
    outliers: list[dict[str, Any]] = Field(
        description="Найденные выбросы по колонкам: сколько, границы, "
                    "примеры значений")
    untouched: list[str] = Field(
        description="Что очистка намеренно оставила человеку")
    next_step: str = Field(description=NEXT_STEP)


class ChartSuggestion(BaseModel):
    """Один предложенный график: готовый вызов инструмента."""

    tool: str
    arguments: dict[str, str]
    why: str = Field(description="По какому правилу график выбран")
    built: bool = Field(description="Уже построен в этом анализе")


class SuggestResult(BaseModel):
    """Ответ suggest_charts: какие графики подходят к этим данным."""

    dataset_id: str = Field(description=DATASET_ID)
    suggestions: list[ChartSuggestion]
    next_step: str = Field(description=NEXT_STEP)


class ChartResult(BaseModel):
    """Текстовая часть ответа инструмента с графиком."""

    dataset_id: str
    title: str
    file: str = Field(description="Путь к PNG от корня репозитория")
    facts: list[str] = Field(description="Что видно на графике, с числами")
    excluded_outliers: int = Field(
        description="Сколько строк, помеченных как выбросы, не вошло "
                    "в расчёт")
    charts_built: int = Field(description="Сколько графиков уже построено")
    next_step: str = Field(description=NEXT_STEP)


class FindingsResult(BaseModel):
    """Ответ collect_findings: цифры, на которых строятся выводы."""

    dataset_id: str = Field(description=DATASET_ID)
    facts: dict[str, Any] = Field(
        description="Итоги, динамика, сезонность, разрезы по категориям, "
                    "корреляции и сведения об очистке")
    how_to_use: str = Field(description="Как писать выводы по этим цифрам")
    next_step: str = Field(description=NEXT_STEP)


class ReportResult(BaseModel):
    """Ответ save_report: где лежит отчёт и что в него вошло."""

    dataset_id: str = Field(description=DATASET_ID)
    report_path: str = Field(description="Путь к отчёту от корня "
                                         "репозитория")
    charts: int = Field(description="Сколько графиков в отчёте")
    warnings: list[str] = Field(
        description="Чего отчёту не хватает. Пустой список: всё на месте")
    next_step: str = Field(description=NEXT_STEP)
