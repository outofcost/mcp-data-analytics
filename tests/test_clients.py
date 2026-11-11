"""Чистые функции клиентов: то, что проверяется без сети и модели."""

import asyncio
import json
import base64
import sys
from pathlib import Path

import httpx2
from mcp.types import CallToolResult, ImageContent, TextContent

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "clients"))

import console_client  # noqa: E402
import telegram_bot  # noqa: E402

from analytics_mcp.skills import loading  # noqa: E402


def test_bot_accepts_the_same_files_as_the_server():
    """Бот не принимает файл, который сервер потом отклонит."""
    assert telegram_bot.ALLOWED_EXTENSIONS == (
        loading.CSV_TYPES | loading.EXCEL_TYPES)


def test_bot_starts_the_server_restricted_to_data_folder():
    """Под ботом сервер читает только папку data/."""
    assert telegram_bot.BOT_SERVER[-1] == "--data-only"
    bot = telegram_bot.TelegramBot("123:TEST")
    assert bot.server_command == telegram_bot.BOT_SERVER


def test_markdown_becomes_telegram_markup():
    """Заголовок и жирный текст жирные, таблица строками, путь без ссылки."""
    text = "\n".join([
        "## Итог",
        "Отчёт: `output/x/report.md`, **рост** 2 < 3",
        "| Показатель | Значение |",
        "|---|---|",
        "| Прибыль | 1 776 705 |",
    ])
    assert telegram_bot.to_telegram_html(text).splitlines() == [
        "<b>Итог</b>",
        "Отчёт: <code>output/x/report.md</code>, <b>рост</b> 2 &lt; 3",
        "Показатель: Значение",
        "Прибыль: 1 776 705",
    ]


def test_long_text_is_split_by_lines():
    """Длинный ответ режется по границам строк и не теряет символы."""
    text = "".join(f"строка {n}\n" for n in range(1000))
    parts = telegram_bot.split_text(text, limit=4000)
    assert all(len(part) <= 4000 for part in parts)
    assert "".join(parts) == text


def test_report_files_are_found_in_tool_answer(tmp_path, monkeypatch):
    """Клиент берёт пути к отчёту из полей ответа сервера."""
    monkeypatch.setattr(console_client, "REPO_ROOT", tmp_path)
    folder = tmp_path / "output" / "x"
    folder.mkdir(parents=True)
    (folder / "report.pdf").write_bytes(b"%PDF")
    answer = ('{"report_path": "output/x/report.md", '
              '"pdf_path": "output/x/report.pdf"}')
    assert console_client.find_report_files(answer) == [
        (folder / "report.pdf").resolve()]


def test_path_from_table_cell_is_not_sent(tmp_path, monkeypatch):
    """Путь, вписанный в ячейку таблицы, в список отправки не попадает."""
    monkeypatch.setattr(console_client, "REPO_ROOT", tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text("чужой файл", encoding="utf-8")
    (tmp_path / "output").mkdir()
    # Так выглядит ответ load_data: значение ячейки лежит в превью.
    preview = json.dumps({
        "dataset_id": "table_1",
        "preview": [{"Комментарий": str(secret), "Файл": "secret.md"}],
        "notes": [f"пример значения: {secret}"],
    }, ensure_ascii=False)
    assert console_client.find_report_files(preview) == []
    # Простой текст с путём тоже ничего не даёт.
    assert console_client.find_report_files(f"см. {secret}") == []
    # Даже поле сервера не выводит за пределы папки output/.
    for value in (str(secret), "secret.md", "output/../secret.md"):
        answer = json.dumps({"pdf_path": value})
        assert console_client.find_report_files(answer) == []


def test_client_takes_the_ready_answer_from_the_server():
    """Клиент берёт текст для пользователя из поля chat_summary."""
    answer = '{"dataset_id": "x", "chat_summary": "**Отчёт**\\nВыводы"}'
    assert console_client.find_chat_summary(answer) == "**Отчёт**\nВыводы"
    assert console_client.find_chat_summary('{"dataset_id": "x"}') == ""
    assert console_client.find_chat_summary("ОШИБКА инструмента") == ""


def test_chart_file_name_is_hidden_from_the_model(tmp_path):
    """Вместо картинки модель видит строку без имени файла."""
    png = base64.b64encode(b"\x89PNG").decode()
    result = CallToolResult(content=[
        TextContent(type="text", text="факты"),
        ImageContent(type="image", data=png, mime_type="image/png")])
    images = []
    text = console_client.result_to_text(result, "plot_trend", tmp_path,
                                         images)
    assert text == "факты\n[график показан пользователю]"
    assert [path.name for path in images] == ["chart_01_plot_trend.png"]


def test_model_request_is_repeated_after_rate_limit(monkeypatch):
    """Отказ 429 клиент повторяет, постоянную ошибку возвращает сразу."""
    monkeypatch.setattr(console_client, "RETRY_PAUSE", 0)
    answers = [429, 429, 200]
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        code = answers[len(calls) - 1]
        body = {"choices": [{"message": {"content": "ок"}}]}
        return httpx2.Response(code, json=body if code == 200 else {})

    async def ask() -> dict:
        async with httpx2.AsyncClient(
                base_url="https://example.test",
                transport=httpx2.MockTransport(handler)) as http:
            return await console_client.ask_model(http, "model", [], [])

    data = asyncio.run(ask())
    assert data["choices"][0]["message"]["content"] == "ок"
    assert len(calls) == 3


def test_bot_keeps_the_real_file_name(tmp_path, monkeypatch):
    """Присланный файл лежит в своей папке под настоящим именем."""
    monkeypatch.setattr(telegram_bot, "UPLOAD_DIR", tmp_path)
    bot = telegram_bot.TelegramBot("123:TEST")

    async def api(method: str, data: dict) -> dict:
        return {"file_path": "documents/file_1.csv"}

    async def get(url: str) -> httpx2.Response:
        return httpx2.Response(200, content=b"a,b\n1,2\n")

    monkeypatch.setattr(bot, "api", api)
    monkeypatch.setattr(bot.http, "get", get)
    path = asyncio.run(bot.download(
        {"file_name": "sales_data.csv", "file_id": "1", "file_size": 8}))
    # Имя файла попадает в шапку отчёта, поэтому отметки времени в нём нет.
    assert path.name == "sales_data.csv"
    assert path.parent.parent == tmp_path
    # Имя папки не угадать по времени отправки: в нём случайный хвост.
    again = asyncio.run(bot.download(
        {"file_name": "sales_data.csv", "file_id": "1", "file_size": 8}))
    assert again.parent != path.parent
    assert len(path.parent.name.rsplit("_", 1)[-1]) == 16
    assert path.read_bytes() == b"a,b\n1,2\n"
