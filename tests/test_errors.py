"""Ошибки приходят ошибками и говорят, что исправить."""

from helpers import Session, run


def test_unknown_dataset_points_to_load_data(tmp_path):
    """Неизвестный dataset_id: ошибка называет load_data."""
    async def scenario(session: Session) -> None:
        reply = await session.call("describe_data", dataset_id="nope")
        assert reply.is_error
        assert "load_data" in reply.text

    run(tmp_path, scenario)


def test_missing_file_lists_available_files(tmp_path):
    """Файла нет: ошибка перечисляет файлы в папке data/."""
    async def scenario(session: Session) -> None:
        reply = await session.call("load_data", file_path="no_such.csv")
        assert reply.is_error
        assert "sales_data.csv" in reply.text

        reply = await session.call("load_data")
        assert reply.is_error
        assert "file_path" in reply.text

    run(tmp_path, scenario)


def test_wrong_column_lists_suitable_columns(tmp_path):
    """Не та колонка: ошибка называет подходящие."""
    async def scenario(session: Session) -> None:
        dataset_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        reply = await session.call("plot_trend", dataset_id=dataset_id,
                                   x_col="Product", y_col="Sales")
        assert reply.is_error
        assert "Подходят: Date" in reply.text

        reply = await session.call("plot_trend", dataset_id=dataset_id,
                                   x_col="Date", y_col="Revenue")
        assert reply.is_error
        assert "Sales, Quantity, Profit" in reply.text

        reply = await session.call("plot_distribution",
                                   dataset_id=dataset_id, col="Date")
        assert reply.is_error
        assert "plot_trend" in reply.text

    run(tmp_path, scenario)


def test_correlation_needs_two_numeric_columns(tmp_path):
    """Одна числовая колонка: корреляции не строятся, ошибка объясняет."""
    async def scenario(session: Session) -> None:
        dataset_id = (await session.call(
            "load_data",
            csv_text="city,amount\nА,1\nБ,2\nА,3\nБ,4")).data["dataset_id"]
        reply = await session.call("correlation_analysis",
                                   dataset_id=dataset_id)
        assert reply.is_error
        assert "минимум две числовые колонки" in reply.text

    run(tmp_path, scenario)


def test_report_needs_conclusions_and_warns_about_skipped_stages(tmp_path):
    """Пустые выводы отклоняются, пропущенные этапы видны в ответе."""
    async def scenario(session: Session) -> None:
        dataset_id = (await session.call(
            "load_data", file_path="sales_data.csv")).data["dataset_id"]
        reply = await session.call("save_report", dataset_id=dataset_id,
                                   title="Отчёт", conclusions=[],
                                   recommendations=["Совет"])
        assert reply.is_error
        assert "conclusions" in reply.text

        reply = await session.call("save_report", dataset_id=dataset_id,
                                   title="Отчёт", conclusions=["Вывод"],
                                   recommendations=["Совет"])
        assert not reply.is_error
        warnings = " ".join(reply.data["warnings"])
        assert "Очистка" in warnings and "Графики" in warnings

    run(tmp_path, scenario)


def test_http_mode_reads_only_data_folder(tmp_path):
    """В режиме HTTP файл вне папки data/ прочитать нельзя."""
    outside = tmp_path / "secret.csv"
    outside.write_text("a,b\n1,2\n", encoding="utf-8")

    async def scenario(session: Session) -> None:
        reply = await session.call("load_data", file_path=str(outside))
        assert reply.is_error
        assert "только из своей папки data/" in reply.text
        reply = await session.call("load_data", file_path="sales_data.csv")
        assert not reply.is_error

    run(tmp_path, scenario, restrict=True)
