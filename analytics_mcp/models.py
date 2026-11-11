"""Формат ответов инструментов и составных аргументов.

Из этих моделей SDK строит выходную схему (``outputSchema``) каждого
инструмента: клиент заранее знает, какие поля придут. В каждом ответе есть
``next_step``: подсказка модели, что вызвать дальше.

``Conclusion`` и ``Recommendation`` задают форму аргументов ``save_report``:
по ним SDK строит входную схему, и любая модель пишет выводы в одном виде.

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


class FilesResult(BaseModel):
    """Ответ list_data_files: какие файлы данных видит сервер."""

    folder: str = Field(description="Папка сервера, где лежат файлы")
    files: list[dict[str, Any]] = Field(
        description="Файлы CSV и Excel: имя для load_data и размер в КБ")
    next_step: str = Field(description=NEXT_STEP)


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
    plan: str = Field(
        description="Порядок этапов анализа и правила работы: тот же "
                    "текст, что в инструкции сервера")
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
        description="Выбросы по колонкам: обычный диапазон, сколько "
                    "грубых (исключены из расчётов) и сколько "
                    "подозрительных (оставлены на проверку), примеры")
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


class Conclusion(BaseModel):
    """Один вывод отчёта: аргумент save_report."""

    headline: str = Field(description=(
        "Утверждение с глаголом, до 8 слов, без тире и без точки "
        "в конце. Пример: «Готовые обеды продаются в убыток»"))
    evidence: str = Field(description=(
        "Одно-два предложения с цифрой из collect_findings, до 180 знаков"))


class Recommendation(BaseModel):
    """Одна рекомендация отчёта: аргумент save_report."""

    action: str = Field(description=(
        "Что сделать: до 10 слов, начинается с глагола в неопределённой "
        "форме. Пример: «Пересчитать цену готовых обедов»"))
    reason: str = Field(description=(
        "Основание: цифра или факт из collect_findings, до 180 знаков"))


class ReportResult(BaseModel):
    """Ответ save_report: готовый текст для чата и где лежит отчёт."""

    dataset_id: str = Field(description=DATASET_ID)
    chat_summary: str = Field(
        description="Готовый ответ пользователю: выводы, рекомендации, что "
                    "сделала очистка и где отчёт. Покажите его без "
                    "изменений")
    report_path: str = Field(description="Путь к отчёту в Markdown от "
                                         "корня репозитория")
    pdf_path: str = Field(description="Путь к тому же отчёту в PDF: один "
                                      "файл с графиками внутри")
    report_url: str = Field(description="Ссылка на PDF для браузера. "
                                        "Пусто, если сервер запущен "
                                        "локально")
    charts: int = Field(description="Сколько графиков в отчёте")
    pages: int = Field(description="Сколько страниц в PDF")
    next_step: str = Field(description=NEXT_STEP)
