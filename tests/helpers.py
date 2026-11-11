"""Общие функции для тестов: сервер во временной папке и вызов инструмента.

Тесты подключаются к серверу настоящим MCP-клиентом из SDK, только без
отдельного процесса: так проверяется то же, что увидит модель.
"""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.types import ImageContent, TextContent

from analytics_mcp.app import build_server
from analytics_mcp.settings import Settings

PNG_SIGNATURE = b"\x89PNG"
# Выводы и рекомендации в форме, которую принимает save_report.
CONCLUSIONS = [
    {"headline": "В декабре продажи выше обычного месяца",
     "evidence": "Декабрь даёт 1,6 от среднего месяца, ноябрь 1,26."},
    {"headline": "Готовые обеды продаются в убыток",
     "evidence": "Прибыль -126 415 при марже -6,9%."},
    {"headline": "Казань растёт быстрее остальных регионов",
     "evidence": "Вторая половина периода к первой: Казань +46,5%."},
]
RECOMMENDATIONS = [
    {"action": "Пересмотреть цену готовых обедов",
     "reason": "Маржа -6,9%, рост продаж увеличивает убыток."},
    {"action": "Подготовить запасы к ноябрю и декабрю",
     "reason": "Эти месяцы дают 1,26 и 1,6 от среднего."},
]


@dataclass
class Reply:
    """Ответ инструмента в удобном для проверок виде."""

    is_error: bool
    text: str
    data: dict[str, Any]
    images: list[bytes]
    structured: dict[str, Any] | None


class Session:
    """Клиент, подключённый к серверу на время одного теста."""

    def __init__(self, client: Client) -> None:
        self.client = client

    async def call(self, name: str, **arguments: Any) -> Reply:
        """Вызывает инструмент и разбирает его ответ."""
        result = await self.client.call_tool(name, arguments)
        texts = [block.text for block in result.content
                 if isinstance(block, TextContent)]
        images = [base64.b64decode(block.data) for block in result.content
                  if isinstance(block, ImageContent)]
        text = texts[0] if texts else ""
        data = {} if result.is_error else json.loads(text)
        return Reply(bool(result.is_error), text, data, images,
                     result.structured_content)


async def analyse(session: Session, file_path: str = "sales_data.csv") -> str:
    """Проходит этапы до отчёта и возвращает dataset_id очищенной таблицы.

    Загрузка, статистика, очистка, три предложенных графика и цифры для
    выводов: после этого save_report готов собрать отчёт.
    """
    raw_id = (await session.call(
        "load_data", file_path=file_path)).data["dataset_id"]
    await session.call("describe_data", dataset_id=raw_id)
    clean_id = (await session.call(
        "clean_data", dataset_id=raw_id)).data["dataset_id"]
    suggested = (await session.call(
        "suggest_charts", dataset_id=clean_id)).data["suggestions"]
    for suggestion in suggested[:3]:
        await session.call(suggestion["tool"], **suggestion["arguments"])
    await session.call("collect_findings", dataset_id=clean_id)
    return clean_id


def run(tmp_path: Path, scenario: Callable[[Session], Awaitable[None]],
        restrict: bool = False, public_url: str = "") -> None:
    """Запускает сценарий теста на сервере с папкой вывода в tmp_path.

    ``restrict`` и ``public_url`` включают то, что отличает режим HTTP:
    чтение только из папки data/ и ссылку на отчёт.
    """
    settings = Settings(output_dir=tmp_path / "output",
                        restrict_to_data_dir=restrict, public_url=public_url)

    async def main() -> None:
        async with Client(build_server(settings)) as client:
            await scenario(Session(client))

    asyncio.run(main())
