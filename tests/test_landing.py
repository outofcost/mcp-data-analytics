"""Страница сервера: инструменты совпадают со схемой, внешних ресурсов нет."""

import html
import json
import re

from scripts import build_landing


def read_schema() -> dict:
    """Читает спецификацию сервера, из которой собирается страница."""
    return json.loads(build_landing.SCHEMA_PATH.read_text(encoding="utf-8"))


def test_page_lists_every_tool_from_schema():
    """На странице стоит каждый инструмент схемы: имя и русское название."""
    schema = read_schema()
    page = build_landing.build_page(schema)
    for tool in schema["tools"]:
        assert f"<code>{tool['name']}</code>" in page
        assert html.escape(tool["title"]) in page
    assert page.count("<li><code>") == len(schema["tools"])


def test_new_tool_appears_with_first_sentence_only():
    """Новый инструмент попадает на страницу без подсказок для модели."""
    schema = read_schema()
    schema["tools"].append({
        "name": "forecast_sales",
        "title": "Прогноз продаж",
        "description": "Строит прогноз на три\nмесяца. Нужен год данных."
                       "\n\nВызывайте после очистки.",
    })
    page = build_landing.build_page(schema)
    assert ("<li><code>forecast_sales</code><span>Прогноз продаж</span>"
            "<p>Строит прогноз на три месяца.</p></li>") in page
    assert "Нужен год данных" not in page
    assert "Вызывайте после очистки" not in page


def test_page_has_no_external_resources():
    """Страница не грузит ничего со стороны и ссылается на три адреса."""
    page = build_landing.build_page(read_schema())
    allowed = (build_landing.SERVER_URL, build_landing.BOT_URL,
               build_landing.REPO_URL)
    urls = re.findall(r"https?://[^\s\"'<>«»]+", page)
    assert urls
    for url in urls:
        assert url.startswith(allowed), url
    for marker in ("<link", "<img", "<iframe", " src=", "@import", "url(",
                   "fetch(", "XMLHttpRequest"):
        assert marker not in page, marker


def test_committed_page_matches_schema():
    """docs/index.html в репозитории собран из текущей схемы."""
    committed = build_landing.PAGE_PATH.read_text(encoding="utf-8")
    assert committed == build_landing.build_page(read_schema()), (
        "Страница устарела. Пересоберите: python scripts/build_landing.py")


def test_config_block_is_valid_json_with_server_address():
    """Блок настроек со страницы разбирается и ведёт на адрес сервера."""
    config = json.loads(build_landing.CONFIG)
    assert config == {"mcpServers": {
        "analytics": {"url": build_landing.SERVER_URL}}}
    page = build_landing.build_page(read_schema())
    assert html.escape(build_landing.CONFIG) in page
