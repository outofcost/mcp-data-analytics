"""Форма отчёта: что save_report принимает и что отклоняет."""

import re

from helpers import CONCLUSIONS, RECOMMENDATIONS, Session, run

from analytics_mcp.report import word_count
from analytics_mcp.report_pdf import ReportPdf


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


def test_report_sections_go_in_the_same_order_in_markdown_and_pdf(
        tmp_path, monkeypatch):
    """Отчёт начинается с ответа: числа, выводы, графики, журнал в конце."""
    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        clean_id = (await session.call(
            "clean_data", dataset_id=raw_id)).data["dataset_id"]
        suggested = (await session.call(
            "suggest_charts", dataset_id=clean_id)).data["suggestions"]
        for suggestion in suggested[:3]:
            await session.call(suggestion["tool"], **suggestion["arguments"])
        await session.call("collect_findings", dataset_id=clean_id)
        report = (await session.call(
            "save_report", dataset_id=clean_id, title="Продажи 2023–2024",
            conclusions=CONCLUSIONS, recommendations=RECOMMENDATIONS)).data

        folder = tmp_path / "output" / raw_id
        text = (folder / "report.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        headings = [line[3:] for line in lines if line.startswith("## ")]
        assert headings == [
            "Главное", "Выводы", "Рекомендации", "Графики",
            "Что сделано с данными",
            "Приложение. Цифры, на которых стоят выводы"]
        # Шапка одной строкой: настоящее имя файла, период, число строк.
        assert lines[2].startswith(
            "sales_data.csv · 01.01.2023 – 25.12.2024 · 190 строк в расчёте")
        assert "- Продажи: 10 046 660" in lines
        assert "- Период: 24 месяца" in lines
        assert ("2. **Готовые обеды продаются в убыток.** Прибыль "
                "−126 415 при марже −6,9%.") in lines
        # Имена колонок из файла в тексте отчёта заменены подписями.
        assert "- Заполнил пропуски в колонке «Прибыль» медианой" in text
        for name in ("Sales", "Profit", "Quantity", "Region", "Product"):
            assert name not in text, name

        # В PDF те же разделы в том же порядке. Текст в PDF сжат, поэтому
        # порядок записан при сборке, а число страниц сверено с файлом.
        assert drawn[:4] == headings[1:5]
        pdf = (folder / "report.pdf").read_bytes()
        assert report["pages"] == len(re.findall(rb"/Type /Page\b", pdf)) == 3

    drawn = []
    section = ReportPdf.section
    monkeypatch.setattr(
        ReportPdf, "section",
        lambda pdf, title: (drawn.append(title), section(pdf, title))[1])
    run(tmp_path, scenario)


def test_chat_summary_is_built_by_the_server(tmp_path):
    """save_report возвращает готовый ответ для чата без имён графиков."""
    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        await session.call("describe_data", dataset_id=raw_id)
        clean_id = (await session.call(
            "clean_data", dataset_id=raw_id)).data["dataset_id"]
        suggested = (await session.call(
            "suggest_charts", dataset_id=clean_id)).data["suggestions"]
        for suggestion in suggested[:3]:
            await session.call(suggestion["tool"], **suggestion["arguments"])
        await session.call("collect_findings", dataset_id=clean_id)
        report = (await session.call(
            "save_report", dataset_id=clean_id, title="Продажи 2023–2024",
            conclusions=CONCLUSIONS, recommendations=RECOMMENDATIONS)).data
        assert report["chat_summary"].splitlines() == [
            "**Продажи 2023–2024**",
            "Данные: sales_data.csv, 01.01.2023 – 25.12.2024, 190 строк "
            "в расчёте.",
            "",
            "**Выводы**",
            "1. В декабре продажи выше обычного месяца. Декабрь даёт 1,6 "
            "от среднего месяца, ноябрь 1,26.",
            "2. Готовые обеды продаются в убыток. Прибыль −126 415 при "
            "марже −6,9%.",
            "3. Казань растёт быстрее остальных регионов. Вторая половина "
            "периода к первой: Казань +46,5%.",
            "",
            "**Что сделать**",
            "1. Пересмотреть цену готовых обедов.",
            "2. Подготовить запасы к ноябрю и декабрю.",
            "",
            "Очистка: удалил 3 дубликата, заполнил 9 пропусков, исключил "
            "из расчёта 2 строки с выбросами.",
            f"Полный отчёт: {report['pdf_path']}, 3 страницы, 3 графика.",
        ]
        assert "chart_" not in report["chat_summary"]
        assert "chat_summary" in report["next_step"]

    run(tmp_path, scenario)


def test_chat_summary_ends_with_the_link_in_http_mode(tmp_path):
    """По HTTP в ответе для чата стоит ссылка на отчёт, пути к файлу нет."""
    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        report = (await session.call(
            "save_report", dataset_id=raw_id, title="Отчёт",
            conclusions=CONCLUSIONS, recommendations=RECOMMENDATIONS)).data
        last = report["chat_summary"].splitlines()[-1]
        assert last == (f"Полный отчёт: {report['report_url']}, 1 страница, "
                        "0 графиков.")
        # Без очистки и без collect_findings ответ это говорит прямо.
        assert "Очистка не выполнялась." in report["chat_summary"]

    run(tmp_path, scenario, public_url="https://example.test")
