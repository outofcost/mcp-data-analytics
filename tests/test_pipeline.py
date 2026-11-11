"""Полная цепочка анализа на тестовых данных из задания."""

from pathlib import Path

from helpers import PNG_SIGNATURE, Session, run

ASSIGNMENT_TOOLS = {"load_data", "describe_data", "plot_trend",
                    "plot_distribution", "correlation_analysis"}


def test_tools_match_assignment_and_are_described(tmp_path):
    """Инструменты из задания есть, у каждого аргумента есть описание."""
    async def scenario(session: Session) -> None:
        tools = (await session.client.list_tools()).tools
        names = {tool.name for tool in tools}
        assert ASSIGNMENT_TOOLS <= names
        for tool in tools:
            assert tool.description, tool.name
            for argument, schema in tool.input_schema["properties"].items():
                assert schema.get("description"), (tool.name, argument)
        by_name = {tool.name: tool for tool in tools}
        # У инструментов есть название для пользователя.
        assert by_name["load_data"].title == (
            "Загрузить данные из CSV или Excel")
        # Описание называет файлы в папке: так клиент находит инструмент,
        # когда пользователь упомянул файл по имени.
        assert "sales_data.csv" in by_name["list_data_files"].description
        # Необязательные аргументы необязательны.
        assert "required" not in by_name["load_data"].input_schema
        assert by_name["clean_data"].input_schema["required"] == [
            "dataset_id"]
        # У инструментов без картинки описан формат ответа.
        assert by_name["load_data"].output_schema["properties"]["next_step"]

    run(tmp_path, scenario)


def test_list_data_files_shows_server_folder(tmp_path):
    """Список файлов называет данные сервера и следующий шаг."""
    async def scenario(session: Session) -> None:
        reply = (await session.call("list_data_files")).data
        names = [item["name"] for item in reply["files"]]
        assert {"sales_data.csv", "orders_dirty.xlsx"} <= set(names)
        assert "load_data" in reply["next_step"]

    run(tmp_path, scenario)


def test_full_chain_on_sales_data(tmp_path):
    """Загрузка, очистка, три графика, цифры и отчёт на sales_data.csv."""
    async def scenario(session: Session) -> None:
        loaded = (await session.call("load_data",
                                     file_path="sales_data.csv")).data
        assert loaded["rows"] == 195
        assert loaded["duplicates"] == 3
        roles = {c["name"]: c["role"] for c in loaded["columns"]}
        assert roles == {"Date": "date", "Product": "category",
                         "Region": "category", "Sales": "number",
                         "Quantity": "number", "Profit": "number"}

        raw_id = loaded["dataset_id"]
        described = (await session.call("describe_data",
                                        dataset_id=raw_id)).data
        assert described["missing"] == {"Region": 2, "Quantity": 4,
                                        "Profit": 3}

        cleaned = (await session.call("clean_data", dataset_id=raw_id)).data
        assert cleaned["rows_before"] == 195
        assert cleaned["rows_after"] == 192
        assert "удалил полные дубликаты строк: 3" in cleaned["actions"]
        clean_id = cleaned["dataset_id"]
        assert clean_id != raw_id

        suggested = (await session.call("suggest_charts",
                                        dataset_id=clean_id)).data
        assert suggested["suggestions"][0]["tool"] == "plot_trend"
        for suggestion in suggested["suggestions"][:3]:
            chart = await session.call(suggestion["tool"],
                                       **suggestion["arguments"])
            assert not chart.is_error
            assert chart.images[0].startswith(PNG_SIGNATURE)
            assert Path(chart.data["file"]).is_file()

        facts = (await session.call("collect_findings",
                                    dataset_id=clean_id)).data["facts"]
        # Три закономерности, заложенные генератором данных.
        assert "декабрь" in facts["сезонность"]["самые_сильные_месяцы"]
        growth = facts["по_категориям"]["Region"][
            "вторая_половина_периода_к_первой_процент"]
        named = {k: v for k, v in growth.items() if k != "Не указано"}
        assert max(named, key=named.get) == "Казань"
        assert list(facts["по_категориям"]["Product"][
            "отрицательная_прибыль"]) == ["Готовые обеды"]

        report = (await session.call(
            "save_report", dataset_id=clean_id, title="Продажи 2023–2024",
            conclusions=["В декабре продажи выше обычного месяца."],
            recommendations=["Пересмотреть цену готовых обедов."])).data
        assert report["charts"] == 3
        assert report["warnings"] == []
        text = (tmp_path / "output" / raw_id / "report.md").read_text(
            encoding="utf-8")
        assert text.count("![") == 3
        assert "Пересмотреть цену готовых обедов." in text
        # Тот же отчёт одним файлом: PDF с тремя графиками внутри.
        assert report["pdf_path"].endswith("report.pdf")
        pdf = (tmp_path / "output" / raw_id / "report.pdf").read_bytes()
        assert pdf.startswith(b"%PDF")
        assert pdf.count(b"/Subtype /Image") == 3
        # Локально ссылки нет: отчёт лежит на машине пользователя.
        assert report["report_url"] == ""

    run(tmp_path, scenario)


def test_report_link_in_http_mode(tmp_path):
    """По HTTP save_report возвращает ссылку на PDF со случайным ключом."""
    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        urls = [
            (await session.call(
                "save_report", dataset_id=raw_id, title="Отчёт",
                conclusions=["Вывод"], recommendations=["Совет"],
            )).data["report_url"]
            for _ in range(2)]
        for url in urls:
            assert url.startswith("https://example.test/reports/")
            assert url.endswith("/report.pdf")
        # Ключ каждый раз новый: по старой ссылке новый отчёт не угадать.
        assert urls[0] != urls[1]

    run(tmp_path, scenario, public_url="https://example.test")


def test_next_step_leads_through_stages_in_order(tmp_path):
    """Каждый ответ называет следующий шаг, этапы идут по порядку."""
    async def scenario(session: Session) -> None:
        reply = (await session.call("load_data",
                                    file_path="sales_data.csv")).data
        raw_id = reply["dataset_id"]
        # Порядок анализа приходит в первом ответе: не каждый клиент
        # передаёт модели instructions сервера.
        assert reply["plan"] == session.client.instructions
        assert "describe_data" in reply["next_step"]
        reply = (await session.call("describe_data", dataset_id=raw_id)).data
        assert "clean_data" in reply["next_step"]
        reply = (await session.call("clean_data", dataset_id=raw_id)).data
        clean_id = reply["dataset_id"]
        assert "suggest_charts" in reply["next_step"]
        reply = (await session.call("suggest_charts",
                                    dataset_id=clean_id)).data
        assert "0 из 3" in reply["next_step"]
        for number, suggestion in enumerate(reply["suggestions"][:3], 1):
            chart = (await session.call(suggestion["tool"],
                                        **suggestion["arguments"])).data
            expected = f"{number} из 3" if number < 3 else "collect_findings"
            assert expected in chart["next_step"]
        reply = (await session.call("collect_findings",
                                    dataset_id=clean_id)).data
        assert "save_report" in reply["next_step"]
        reply = (await session.call("save_report", dataset_id=clean_id,
                                    title="Отчёт", conclusions=["Вывод"],
                                    recommendations=["Совет"])).data
        assert reply["next_step"].startswith("Анализ завершён")

    run(tmp_path, scenario)


def test_outliers_are_flagged_and_left_for_a_human(tmp_path):
    """Грубые выбросы помечаются и не считаются, спорные остаются."""
    async def scenario(session: Session) -> None:
        raw_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        flagged = (await session.call("clean_data", dataset_id=raw_id)).data
        assert flagged["rows_after"] == 192
        sales = flagged["outliers"][0]
        assert sales["column"] == "Sales"
        # Две опечатки с лишним нулём исключены из расчётов.
        assert sales["gross_examples"] == [549300, 405700]
        assert flagged["untouched"]
        chart = (await session.call(
            "plot_distribution", dataset_id=flagged["dataset_id"],
            col="Sales")).data
        assert chart["excluded_outliers"] == 2

        removed = (await session.call("clean_data", dataset_id=raw_id,
                                      outliers="remove")).data
        assert removed["rows_after"] == 190
        # Повторная очистка сбрасывает графики, построенные до неё.
        assert any("сбросил" in action for action in removed["actions"])

    run(tmp_path, scenario)
