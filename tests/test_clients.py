"""Чистые функции клиентов: то, что проверяется без сети и модели."""

import sys
from pathlib import Path

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
        "Показатель · Значение",
        "Прибыль · 1 776 705",
    ]


def test_long_text_is_split_by_lines():
    """Длинный ответ режется по границам строк и не теряет символы."""
    text = "".join(f"строка {n}\n" for n in range(1000))
    parts = telegram_bot.split_text(text, limit=4000)
    assert all(len(part) <= 4000 for part in parts)
    assert "".join(parts) == text


def test_report_files_are_found_in_tool_answer(tmp_path, monkeypatch):
    """Клиент находит в ответе инструмента пути к существующим отчётам."""
    monkeypatch.setattr(console_client, "REPO_ROOT", tmp_path)
    folder = tmp_path / "output" / "x"
    folder.mkdir(parents=True)
    (folder / "report.pdf").write_bytes(b"%PDF")
    answer = ('{"report_path": "output/x/report.md", '
              '"pdf_path": "output/x/report.pdf"}')
    assert console_client.find_report_files(answer) == [
        folder / "report.pdf"]
