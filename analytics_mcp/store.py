"""Хранилище загруженных таблиц.

DataFrame нельзя передать через MCP: протокол возит JSON. Поэтому таблица
остаётся в памяти сервера, а модель получает короткий ``dataset_id`` и
передаёт его в остальные инструменты.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from mcp.server.mcpserver.exceptions import ToolError

from analytics_mcp.columns import OUTLIER_COLUMN


@dataclass
class Chart:
    """Построенный график: нужен, чтобы собрать отчёт."""

    key: str  # инструмент и аргументы: повторный вызов заменяет график
    title: str
    path: Path
    facts: list[str]


@dataclass
class Analysis:
    """Состояние одного анализа: что уже сделано с исходным файлом.

    Исходная таблица и таблица после очистки делят одно состояние. По нему
    скиллы определяют, выполнен ли их этап, а отчёт собирает графики.
    """

    root_id: str
    source: str
    described: bool = False
    clean_id: str | None = None
    cleaning_log: list[str] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    findings: dict[str, Any] | None = None
    report_path: Path | None = None
    # Место для данных новых скиллов, чтобы не менять этот класс.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def current_id(self) -> str:
        """Идентификатор таблицы, с которой сейчас нужно работать."""
        return self.clean_id or self.root_id


@dataclass
class Dataset:
    """Таблица в памяти сервера вместе с тем, что о ней известно."""

    dataset_id: str
    frame: pd.DataFrame
    roles: dict[str, str]
    analysis: Analysis
    notes: list[str] = field(default_factory=list)

    def working_frame(self) -> tuple[pd.DataFrame, int]:
        """Возвращает строки для расчётов и число исключённых выбросов.

        Строки, которые очистка пометила как выбросы, остаются в таблице,
        но в графики и итоги не входят. Инструменты сообщают их число.
        """
        if OUTLIER_COLUMN not in self.frame.columns:
            return self.frame, 0
        flagged = self.frame[OUTLIER_COLUMN]
        return self.frame[~flagged], int(flagged.sum())


class DatasetStore:
    """Выдаёт идентификаторы таблицам и возвращает таблицы по ним."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}
        self._counter = 0

    def add(self, frame: pd.DataFrame, roles: dict[str, str], source: str,
            notes: list[str]) -> Dataset:
        """Сохраняет новую таблицу и начинает для неё анализ."""
        self._counter += 1
        stem = re.sub(r"[^a-z0-9]+", "_", Path(source).stem.lower())
        dataset_id = f"{stem.strip('_') or 'data'}_{self._counter}"
        dataset = Dataset(dataset_id, frame, roles,
                          Analysis(dataset_id, source), notes)
        self._datasets[dataset_id] = dataset
        return dataset

    def derive(self, parent: Dataset, frame: pd.DataFrame,
               roles: dict[str, str], suffix: str) -> Dataset:
        """Сохраняет таблицу, полученную из другой, в том же анализе."""
        dataset_id = f"{parent.analysis.root_id}_{suffix}"
        dataset = Dataset(dataset_id, frame, roles, parent.analysis,
                          list(parent.notes))
        self._datasets[dataset_id] = dataset
        return dataset

    def get(self, dataset_id: str) -> Dataset:
        """Возвращает таблицу или ошибку с подсказкой, что исправить."""
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            known = ", ".join(self._datasets) or "пока нет ни одного"
            raise ToolError(
                f"Набор данных «{dataset_id}» не найден. Загруженные наборы: "
                f"{known}. Сначала вызовите load_data и передайте dataset_id "
                "из его ответа."
            )
        return dataset
