"""Расширяемость: новый скилл подключается без правок ядра."""

from typing import Annotated

from pydantic import Field

from analytics_mcp import registry
from analytics_mcp.registry import Skill, register_skill, tool
from helpers import Session, run


def test_new_skill_is_picked_up_without_core_changes(tmp_path):
    """Достаточно объявить класс: инструмент и этап появляются сами."""

    @register_skill
    class RowCountSkill(Skill):
        """Пробный скилл: один инструмент, считает строки."""

        stage = 35
        title = "Проба расширения"
        guide = "Считает строки таблицы."

        @tool
        def count_rows(
            self,
            dataset_id: Annotated[str, Field(description="Таблица")],
        ) -> int:
            """Возвращает число строк таблицы."""
            return len(self.store.get(dataset_id).frame)

    async def scenario(session: Session) -> None:
        names = [t.name for t in (await session.client.list_tools()).tools]
        # Этап 35 встал между графиками (30) и выводами (40).
        assert names.index("correlation_analysis") < names.index(
            "count_rows") < names.index("collect_findings")
        assert "Проба расширения (RowCountSkill): count_rows" in (
            session.client.instructions)
        dataset_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        reply = await session.call("count_rows", dataset_id=dataset_id)
        assert reply.structured == {"result": 195}

    try:
        run(tmp_path, scenario)
    finally:
        registry._SKILLS.pop("RowCountSkill")


def test_abc_skill_added_as_one_file(tmp_path):
    """ABC-анализ: группы считаются, убыточный показатель отклоняется."""
    async def scenario(session: Session) -> None:
        dataset_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        dataset_id = (await session.call(
            "clean_data", dataset_id=dataset_id)).data["dataset_id"]
        reply = await session.call("abc_analysis", dataset_id=dataset_id,
                                   col="Region")
        assert reply.images
        group_a = reply.data["facts"][1]
        assert group_a.startswith("Группа A (") and "Москва" in group_a

        reply = await session.call("abc_analysis", dataset_id=dataset_id,
                                   col="Product", value_col="Profit")
        assert reply.is_error
        assert "Готовые обеды" in reply.text

    run(tmp_path, scenario)
