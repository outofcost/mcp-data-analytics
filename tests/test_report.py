"""Форма отчёта: что save_report принимает и что отклоняет."""

from helpers import CONCLUSIONS, RECOMMENDATIONS, Session, run

from analytics_mcp.report import word_count


def test_schema_tells_the_model_the_shape_of_a_conclusion(tmp_path):
    """Схема save_report называет поля пункта и границы числа пунктов."""
    async def scenario(session: Session) -> None:
        tools = (await session.client.list_tools()).tools
        schema = next(tool.input_schema for tool in tools
                      if tool.name == "save_report")
        conclusions = schema["properties"]["conclusions"]
        assert (conclusions["minItems"], conclusions["maxItems"]) == (3, 5)
        recommendations = schema["properties"]["recommendations"]
        assert (recommendations["minItems"],
                recommendations["maxItems"]) == (2, 4)
        point = schema["$defs"]["Conclusion"]
        assert point["required"] == ["headline", "evidence"]
        assert "8 слов" in point["properties"]["headline"]["description"]
        assert schema["$defs"]["Recommendation"]["required"] == [
            "action", "reason"]

    run(tmp_path, scenario)


def test_wrong_shape_is_rejected_with_every_violation_listed(tmp_path):
    """Все нарушения приходят одной ошибкой по-русски, с номером пункта."""
    async def scenario(session: Session) -> None:
        dataset_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        long_headline = ("Продажи готовых обедов растут быстрее остальных "
                         "товаров, но приносят убыток компании")
        conclusions = [
            {"headline": long_headline, "evidence": "Маржа -6,9%."},
            {"headline": "Казань растёт", "evidence": "Рост заметный."},
            {"headline": "Декабрь сильнее", "evidence": "Индекс 1,6. " * 20},
        ] + CONCLUSIONS
        recommendations = [{"action": "", "reason": "Маржа -6,9%."}]
        reply = await session.call(
            "save_report", dataset_id=dataset_id, title="Отчёт",
            conclusions=conclusions, recommendations=recommendations)
        assert reply.is_error
        problems = [line for line in reply.text.splitlines()
                    if line.startswith("- ")]
        assert problems == [
            "- conclusions: пунктов 6, нужно от 3 до 5. Оставьте самые "
            "важные.",
            "- conclusions, пункт 1, headline: слов 11, нужно не больше 8. "
            "Подробности перенесите в evidence.",
            "- conclusions, пункт 2, evidence: нет ни одной цифры. Добавьте "
            "число из collect_findings.",
            "- conclusions, пункт 3, evidence: знаков 239, нужно не больше "
            "180. Оставьте одно-два предложения.",
            "- recommendations: пунктов 1, нужно от 2 до 4. Добавьте "
            "недостающие.",
            "- recommendations, пункт 1, action: пусто. Напишите фразу до "
            "10 слов.",
        ]
        assert "Исправьте и вызовите снова" in reply.text
        # Отклонённый вызов отчёта не создаёт.
        assert not list((tmp_path / "output").glob("*/report.*"))

        fixed = await session.call(
            "save_report", dataset_id=dataset_id, title="Отчёт",
            conclusions=CONCLUSIONS, recommendations=RECOMMENDATIONS)
        assert not fixed.is_error

    run(tmp_path, scenario)


def test_number_with_spaces_counts_as_one_word():
    """Число с разрядами идёт за одно слово, текст в скобках не в счёт."""
    assert word_count("Выручка за год составила 5 215 415 руб.") == 6
    assert word_count("Сыр даёт пятую часть продаж (21,8%, 2 190 560)") == 5
    assert word_count("   ") == 0
