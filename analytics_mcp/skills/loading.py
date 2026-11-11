"""Скилл загрузки: читает файл и определяет структуру данных."""

import csv
import io
import re
from pathlib import Path
from collections.abc import Callable
from typing import Annotated, Any
from zipfile import BadZipFile

import pandas as pd
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from analytics_mcp import columns as col
from analytics_mcp.models import (ColumnInfo, DescribeResult, FilesResult,
                                  LoadResult)
from analytics_mcp.registry import Skill, register_skill, tool
from analytics_mcp.store import Analysis

CSV_TYPES = {".csv", ".tsv", ".txt"}
EXCEL_TYPES = {".xlsx", ".xlsm"}
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TEXT_CHARS = 300_000
# В первых строках файла ищем строку заголовка.
HEADER_SEARCH_ROWS = 20
# Строка итогов: первая заполненная ячейка начинается со слов «Итого» или
# «Всего» либо целиком равна «Total». Английское слово берём только целиком:
# с него может начинаться название товара.
TOTAL_ROW = re.compile(
    r"(общий итог|итого|всего)\b|(grand )?total[\s:]*$", re.IGNORECASE)


def format_value(value: object) -> str:
    """Пишет значение ячейки коротко: дату без времени, целое без дроби."""
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}"
    return str(value)


def decode(data: bytes) -> tuple[str, str]:
    """Декодирует файл: UTF-8, а если не вышло, кодировка Windows."""
    try:
        return data.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace"), "Windows-1251"


def read_csv_text(text: str) -> tuple[pd.DataFrame, str]:
    """Читает CSV в таблицу строк без заголовка и возвращает разделитель."""
    try:
        delimiter = csv.Sniffer().sniff(text[:5000], ",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    width = max((len(row) for row in rows), default=0)
    if width == 0:
        raise ToolError("Файл пустой: в нём нет ни одной строки с данными.")
    padded = [row + [""] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded, dtype="string"), delimiter


def split_header(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Находит строку заголовка и отделяет её от данных.

    В выгрузках из учётных систем над таблицей часто стоит название отчёта
    и реквизиты, а под ней строка «Итого». Заголовком считается первая
    строка, в которой заполнено большинство колонок. Строки итогов
    в таблицу не попадают: иначе сумма по колонке удвоится.
    """
    text = raw.apply(col.as_text)
    filled = text.notna()
    counts = filled.sum(axis=1)
    head = counts.iloc[:HEADER_SEARCH_ROWS]
    # Больше половины от самой заполненной строки: строка реквизитов
    # с двумя ячейками над таблицей из четырёх колонок сюда не подходит.
    need = head.max() // 2 + 1
    candidates = head[head >= need]
    if candidates.empty:
        raise ToolError("В файле не нашлось строки заголовка: первые строки "
                        "пустые. Проверьте, что в файле есть таблица.")
    header_position = raw.index.get_loc(candidates.index[0])
    notes = []
    if header_position:
        notes.append(f"заголовок таблицы нашёл в строке {header_position + 1},"
                     f" строки над ним пропустил: {header_position}")

    names: list[str] = []
    for number, value in enumerate(raw.iloc[header_position], start=1):
        name = "" if pd.isna(value) else str(value).strip()
        name = name or f"Колонка {number}"
        while name in names:
            name += " (повтор)"
        names.append(name)

    data = raw.iloc[header_position + 1:].copy()
    data.columns = names
    below = text.iloc[header_position + 1:]
    has_values = below.notna().any(axis=1)
    empty_rows = int((~has_values).sum())
    if empty_rows:
        notes.append(f"пропустил пустые строки: {empty_rows}")
    first_cell = below.iloc[:, 0]
    for position in range(1, below.shape[1]):
        first_cell = first_cell.fillna(below.iloc[:, position])
    is_total = first_cell.str.match(TOTAL_ROW, na=False)
    if is_total.any():
        notes.append("убрал строки итогов (первая заполненная ячейка "
                     "начинается с «Итого», «Всего» или «Total»): "
                     f"{int(is_total.sum())}")
    keep = (has_values & ~is_total).to_numpy()
    return data[keep].reset_index(drop=True), notes


@register_skill
class DataLoadingSkill(Skill):
    """Этап 1. Загружает данные, выводит структуру, записи и пропуски."""

    stage = 10
    title = "Загрузка"
    guide = ("Читает файл, определяет типы колонок, считает пропуски и "
             "дубликаты.")
    rules = (
        "Таблица адресуется по dataset_id из ответа load_data.",
        "Если пользователь назвал файл по имени, сначала вызови load_data "
        "с этим именем: файлы лежат в папке data/ сервера, прикреплять их "
        "к чату не нужно. list_data_files покажет, какие файлы есть.",
        "Если пользователь прикрепил таблицу к чату и файла на сервере "
        "нет, передай её текст в аргументе csv_text инструмента load_data.",
    )

    def is_done(self, analysis: Analysis) -> bool:
        """Этап выполнен, когда по таблице получена статистика."""
        return analysis.described

    def hint(self, analysis: Analysis) -> str:
        """Подсказывает получить статистику по загруженной таблице."""
        return (f"Вызовите describe_data(dataset_id=\"{analysis.root_id}\"), "
                "чтобы увидеть базовую статистику.")

    def _resolve(self, file_path: str) -> Path:
        """Находит файл на диске или объясняет, почему его нельзя прочитать."""
        settings = self.settings
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            options = [settings.root / path, settings.data_dir / path]
            path = next((p for p in options if p.exists()), options[0])
        path = path.resolve()
        available = self._available_files()

        inside = path.is_relative_to(settings.data_dir.resolve())
        if settings.restrict_to_data_dir and not inside:
            raise ToolError(
                "В режиме HTTP сервер читает файлы только из своей папки "
                f"data/. Передайте имя файла оттуда. Сейчас там: {available}."
            )
        if not path.is_file():
            raise ToolError(
                f"Файл «{file_path}» не найден. Передайте полный путь или "
                f"имя файла из папки data/. Сейчас там: {available}."
            )
        if path.suffix.lower() not in CSV_TYPES | EXCEL_TYPES:
            raise ToolError(
                f"Формат «{path.suffix}» не поддерживается. Подходят CSV "
                "(.csv, .tsv, .txt) и Excel (.xlsx, .xlsm). Старый формат "
                ".xls сохраните как .xlsx."
            )
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("Файл больше 30 МБ. Сократите его или разбейте "
                            "на части.")
        return path

    def _data_files(self) -> list[Path]:
        """Находит файлы CSV и Excel в папке data/ сервера.

        Вложенные папки не просматриваются: в data/uploads лежат файлы,
        присланные боту, и их имена другим пользователям показывать нельзя.
        """
        return sorted(path for path in self.settings.data_dir.glob("*")
                      if path.suffix.lower() in CSV_TYPES | EXCEL_TYPES)

    def _available_files(self) -> str:
        """Перечисляет файлы данных в папке data/ одной строкой."""
        folder = self.settings.data_dir
        names = [path.relative_to(folder).as_posix()
                 for path in self._data_files()]
        return ", ".join(names[:20]) or "файлов нет"

    def describe(self, method: Callable[..., Any]) -> str:
        """Дописывает к описанию list_data_files имена файлов в папке.

        Клиент с отложенной загрузкой инструментов ищет их по тексту
        описания. Когда пользователь называет файл по имени, поиск находит
        этот инструмент, и модель узнаёт, что файл лежит на сервере.
        """
        text = super().describe(method)
        if method.__name__ == "list_data_files":
            text += f"\n\nСейчас в папке: {self._available_files()}."
        return text

    @tool(title="Файлы с данными на сервере")
    def list_data_files(self) -> FilesResult:
        """Показывает файлы с данными (CSV, Excel) в папке data/ сервера.

        Вызывайте, когда пользователь называет файл по имени или
        спрашивает, какие данные есть. Файл из этой папки не нужно
        прикреплять к чату: load_data читает его по имени.
        """
        folder = self.settings.data_dir
        files = [{"name": path.relative_to(folder).as_posix(),
                  "size_kb": round(path.stat().st_size / 1024, 1)}
                 for path in self._data_files()]
        if files:
            next_step = ("Вызовите load_data(file_path=\"<имя файла>\") "
                         "с нужным файлом из списка.")
        else:
            next_step = ("Файлов нет. Попросите пользователя положить файл "
                         "в папку data/ или передать таблицу текстом в "
                         "csv_text инструмента load_data.")
        return FilesResult(folder=self.settings.relative(folder),
                           files=files, next_step=next_step)

    def _read(self, path: Path, sheet: str) -> tuple[pd.DataFrame, list[str]]:
        """Читает файл в таблицу без заголовка, все значения как есть."""
        if path.suffix.lower() in CSV_TYPES:
            text, encoding = decode(path.read_bytes())
            raw, delimiter = read_csv_text(text)
            shown = {"\t": "табуляция"}.get(delimiter, f"«{delimiter}»")
            return raw, [f"разделитель {shown}, кодировка {encoding}"]

        try:
            book = pd.ExcelFile(path)
        except (ValueError, BadZipFile) as error:
            raise ToolError(
                f"Файл «{path.name}» не читается как Excel: расширение "
                f"{path.suffix}, но внутри не книга Excel или файл "
                "повреждён. Откройте его в Excel и сохраните заново как "
                ".xlsx или как CSV, потом загрузите снова."
            ) from error
        if sheet and sheet not in book.sheet_names:
            raise ToolError(f"Листа «{sheet}» в файле нет. Есть листы: "
                            f"{', '.join(book.sheet_names)}.")
        name = sheet or book.sheet_names[0]
        raw = pd.read_excel(book, sheet_name=name, header=None,
                            dtype=object)
        notes = [f"прочитал лист «{name}»"]
        if not sheet and len(book.sheet_names) > 1:
            notes.append("в файле есть ещё листы: "
                         f"{', '.join(book.sheet_names[1:])}")
        if raw.empty:
            raise ToolError(f"Лист «{name}» пустой.")
        return raw, notes

    @tool(title="Загрузить данные из CSV или Excel")
    def load_data(
        self,
        file_path: Annotated[str, Field(
            description="Путь к файлу CSV или Excel: полный, от корня "
                        "репозитория или имя файла из папки data/")] = "",
        sheet: Annotated[str, Field(
            description="Имя листа Excel. Пусто: первый лист")] = "",
        csv_text: Annotated[str, Field(
            description="Текст таблицы в формате CSV вместо файла: когда "
                        "пользователь прикрепил или вставил таблицу в чат "
                        "и пути к файлу нет")] = "",
    ) -> LoadResult:
        """Загружает таблицу из файла CSV или Excel. Первый шаг анализа.

        Вызывайте, когда пользователь просит проанализировать данные,
        продажи или файл, построить графики, дать выводы и рекомендации.
        Файл, названный по имени (например, sales_data.csv), ищется в папке
        data/ сервера: прикреплять его к чату не нужно.

        Нужен один из аргументов: file_path или csv_text. Сам находит строку
        заголовка, разделитель и кодировку, определяет тип каждой колонки
        (дата, число, категория), считает пропуски и дубликаты. Возвращает
        dataset_id, по которому остальные инструменты находят таблицу,
        и порядок дальнейшего анализа.
        """
        if csv_text.strip():
            if len(csv_text) > MAX_TEXT_CHARS:
                raise ToolError("Текст длиннее 300 тысяч символов. Положите "
                                "файл в папку data/ и передайте file_path.")
            raw, delimiter = read_csv_text(csv_text.strip())
            source, notes = "текст из чата", [f"разделитель «{delimiter}»"]
        elif file_path.strip():
            path = self._resolve(file_path.strip())
            raw, notes = self._read(path, sheet.strip())
            source = path.name
        else:
            raise ToolError(
                "Не передан ни file_path, ни csv_text. Передайте путь к "
                "файлу. В папке data/ сейчас: "
                f"{self._available_files()}."
            )

        data, header_notes = split_header(raw)
        frame, roles, type_notes, date_questions = col.infer_frame(data)
        notes += header_notes + type_notes
        if frame.empty:
            raise ToolError("В таблице есть заголовок, но нет строк с "
                            "данными.")
        if not col.columns_with_role(roles, col.DATE):
            notes.append("колонки с датой нет: график динамики построить "
                         "не получится")

        stem = "table" if csv_text.strip() else source
        dataset = self.store.add(frame, roles, stem, notes)
        dataset.analysis.source = source
        return LoadResult(
            dataset_id=dataset.dataset_id,
            source=source,
            rows=len(frame),
            columns=[ColumnInfo(
                name=name,
                role=roles[name],
                missing=int(frame[name].isna().sum()),
                unique=int(frame[name].nunique()),
                examples=[format_value(value) for value
                          in frame[name].dropna().unique()[:3]],
            ) for name in frame.columns],
            duplicates=int(frame.duplicated().sum()),
            missing_total=int(frame.isna().sum().sum()),
            notes=notes,
            questions=self._questions(roles) + date_questions,
            preview=[{name: format_value(value)
                      for name, value in row.items()}
                     for row in frame.head(3).to_dict("records")],
            # Не каждый клиент передаёт модели instructions сервера,
            # поэтому порядок анализа приходит и в первом ответе.
            plan=self.workflow.instructions(),
            next_step=self.next_step(dataset),
        )

    @staticmethod
    def _questions(roles: dict[str, str]) -> list[str]:
        """Формулирует вопросы пользователю, если структура неясна."""
        numbers = col.columns_with_role(roles, col.NUMBER)
        if not numbers:
            return ["В таблице нет числовых колонок, считать и строить "
                    "графики не по чему. Спросите пользователя, тот ли "
                    "это файл."]
        if len(numbers) > 1 and not any(
                col.has_word(name, col.MEASURE_WORDS) for name in numbers):
            return ["Непонятно, какая колонка главный показатель: "
                    f"{', '.join(numbers)}. Спросите пользователя. Без "
                    f"ответа анализ пойдёт по колонке «{numbers[0]}»."]
        return []

    @tool(title="Базовая статистика")
    def describe_data(
        self,
        dataset_id: Annotated[str, Field(
            description="Идентификатор таблицы из ответа load_data")],
    ) -> DescribeResult:
        """Считает базовую статистику по таблице.

        Для чисел: количество, сумма, среднее, медиана, минимум, максимум,
        стандартное отклонение. Для категорий: частые значения и их доли.
        Для дат: границы периода. Отдельно пропуски по колонкам.
        """
        dataset = self.store.get(dataset_id)
        frame, roles = dataset.frame, dataset.roles

        numbers = {}
        for name in col.columns_with_role(roles, col.NUMBER):
            values = frame[name].dropna()
            numbers[name] = {key: round(float(value), 2) for key, value in {
                "count": len(values), "sum": values.sum(),
                "mean": values.mean(), "median": values.median(),
                "min": values.min(), "max": values.max(),
                "std": values.std(ddof=0),
            }.items()} if len(values) else {"count": 0.0}

        categories = {}
        for name in col.columns_with_role(roles, col.CATEGORY):
            counts = frame[name].value_counts()
            categories[name] = [
                {"value": value, "rows": int(count),
                 "share_percent": round(100 * count / len(frame), 1)}
                for value, count in counts.head(5).items()]

        dates = {}
        for name in col.columns_with_role(roles, col.DATE):
            values = frame[name].dropna()
            if len(values):
                dates[name] = {
                    "first": values.min().date().isoformat(),
                    "last": values.max().date().isoformat(),
                    "days": int((values.max() - values.min()).days),
                }

        dataset.analysis.described = True
        return DescribeResult(
            dataset_id=dataset_id,
            rows=len(frame),
            numbers=numbers,
            categories=categories,
            dates=dates,
            missing={name: int(count) for name, count
                     in frame.isna().sum().items() if count},
            next_step=self.next_step(dataset),
        )
