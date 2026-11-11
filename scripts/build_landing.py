"""Собирает страницу сервера docs/index.html из docs/tools-schema.json.

Страница открывается через GitHub Pages из папки docs/. Список
инструментов берётся из выгрузки работающего сервера, поэтому после
изменения инструментов страницу пересобирают этой командой и текст на ней
не расходится с сервером. Цвета те же, что на графиках: они читаются из
``analytics_mcp/style.py``.

Запуск из корня репозитория: ``python scripts/build_landing.py``
"""

import html
import json
import re
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics_mcp import style  # noqa: E402

# Адреса, которые стоят на странице. Других внешних ссылок на ней нет:
# это проверяет tests/test_landing.py.
SERVER_URL = "https://affluent-grant-finalize.ngrok-free.dev/mcp"
BOT_URL = "https://t.me/test_vkusvillmcpKK_bot"
REPO_URL = "https://github.com/outofcost/mcp-data-analytics"
# Готовый отчёт по sales_data.csv: путь от корня репозитория.
EXAMPLE_REPORT = "examples/report-sales/report.pdf"

SCHEMA_PATH = ROOT / "docs" / "tools-schema.json"
PAGE_PATH = ROOT / "docs" / "index.html"

# Запрос для чата. Сервер назван по имени: так помощник идёт к нему сразу
# и не пытается разобрать файл своими средствами.
CHAT_REQUEST = (
    "Проанализируй через analytics продажи из файла sales_data.csv, "
    "построй графики и дай рекомендации. Файл лежит на сервере, "
    "прикладывать его не нужно.")

# Блок для файла настроек клиента (Cursor и клиенты с таким же форматом).
CONFIG = json.dumps({"mcpServers": {"analytics": {"url": SERVER_URL}}},
                    indent=2)

# Запасной путь. Помощник не может добавить себе сервер посреди чата,
# но с доступом в сеть может обратиться к серверу напрямую: так прошёл
# облачный агент Cursor.
FALLBACK = f"""\
MCP-сервера analytics у тебя в инструментах нет, из этой сессии его \
не добавить. Работай с ним напрямую: отправляй POST с JSON-RPC на \
{SERVER_URL}, заголовки Content-Type: application/json и Accept: \
application/json, text/event-stream. Сначала initialize, потом tools/list \
и tools/call. Ключ не нужен.
Начни с load_data(file_path="sales_data.csv") и выполняй поле next_step \
из каждого ответа, пока анализ не завершится. В конце покажи chat_summary \
как есть и ссылку на отчёт."""

# Тёмной темы в style.py нет: графики всегда рисуются на белом. Эти цвета
# нужны только странице.
DARK_BACKGROUND = "#111512"
DARK_SURFACE = "#1A211C"
DARK_TEXT = "#ECEEEC"
DARK_MUTED = "#A3A6AB"
DARK_LINE = "#2E3731"
LIGHT_SURFACE = "#F2F8F4"

PAGE = Template("""\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>MCP-сервер для анализа таблиц</title>
<meta name="description" content="MCP-сервер загружает CSV или Excel, \
чистит данные, строит графики и собирает отчёт в PDF.">
<style>
:root {
  --bg: #FFFFFF;
  --surface: $light_surface;
  --text: $text;
  --muted: $grey;
  --line: $light_grey;
  --accent: $dark_green;
  --on-accent: #FFFFFF;
  --mark: $green;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: $dark_background;
    --surface: $dark_surface;
    --text: $dark_text;
    --muted: $dark_muted;
    --line: $dark_line;
    --accent: $green;
    --on-accent: $dark_background;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, Arial,
    sans-serif;
  -webkit-text-size-adjust: 100%;
}
main { max-width: 900px; margin: 0 auto; padding: 36px 20px 44px; }
h1 { margin: 0 0 12px; font-size: 30px; line-height: 1.2; }
h1::before {
  content: "";
  display: block;
  width: 44px;
  height: 5px;
  margin-bottom: 18px;
  border-radius: 3px;
  background: var(--mark);
}
h2 { margin: 30px 0 10px; font-size: 19px; line-height: 1.3; }
p, ol { max-width: 700px; }
p { margin: 0 0 10px; }
.lead { font-size: 18px; }
.note { color: var(--muted); font-size: 15px; }
a { color: var(--accent); text-underline-offset: 3px; }
code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 14px;
}
.box {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.box.short { align-items: center; }
.box code, .box pre {
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 6px 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
button {
  flex: none;
  min-width: 124px;
  padding: 8px 12px;
  border: 0;
  border-radius: 8px;
  background: var(--accent);
  color: var(--on-accent);
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
button:focus-visible, a:focus-visible {
  outline: 2px solid var(--mark);
  outline-offset: 2px;
}
.clients { margin: 0 0 10px; padding-left: 22px; }
.clients li { margin-bottom: 6px; }
.tools {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0 28px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}
.tools li { padding: 10px 0; border-top: 1px solid var(--line); }
.tools code { color: var(--accent); font-weight: 600; }
.tools span { display: block; font-size: 15px; }
.tools p { margin: 2px 0 0; color: var(--muted); font-size: 14px; }
footer {
  margin-top: 30px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
footer p { max-width: none; }
@media (max-width: 860px) {
  .tools { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 600px) {
  main { padding: 28px 16px 40px; }
  h1 { font-size: 25px; }
  .lead { font-size: 17px; }
  .box, .box.short { flex-direction: column; align-items: flex-start; }
  .box code, .box pre { flex: none; width: 100%; padding: 0; }
  .tools { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<main>
<h1>MCP-сервер для анализа таблиц</h1>
<p class="lead">Сервер по протоколу MCP загружает таблицу CSV или Excel, \
чистит данные и строит графики.</p>
<p class="lead">Подключите его к своему ИИ-помощнику: в ответ на запрос \
в чате придут графики, выводы с рекомендациями и отчёт в PDF.</p>
<p>Результат можно посмотреть, ничего не подключая: \
<a href="$repo_url/blob/main/$example_report">пример отчёта \
по sales_data.csv</a> лежит в репозитории. Ссылку на PDF в ответе сервера \
браузер открывает через страницу-предупреждение ngrok: на ней нужно нажать \
кнопку продолжения.</p>

<h2>Подключите сервер по адресу</h2>
<div class="box short">
<code id="server-url">$server_url</code>
<button type="button" data-copy="server-url">Скопировать</button>
</div>

<h2>Добавьте сервер в настройках до начала чата</h2>
<p>Из уже идущего чата помощник сервер себе не добавит.</p>
<ul class="clients">
<li>В Claude откройте Settings, затем Connectors и нажмите \
Add custom connector. Назовите сервер analytics, вставьте адрес \
и выберите вход «No sign in».</li>
<li>В Cursor на компьютере вставьте блок ниже в файл \
<code>~/.cursor/mcp.json</code>. Если сервер не появился в списке, \
перезапустите Cursor.</li>
<li>Для облачного агента Cursor добавьте сервер в списке MCP \
на cursor.com/agents, тип HTTP, и запустите нового агента.</li>
<li>В ChatGPT добавьте в настройках свой MCP-сервер по этому адресу, \
без аутентификации.</li>
</ul>
<div class="box">
<pre id="config">$config</pre>
<button type="button" data-copy="config">Скопировать</button>
</div>
<p class="note">Шаги для Claude я прошёл на этом сервере. Шаги для Cursor \
сверил с его документацией, шаг для ChatGPT не проверял.</p>
<p class="note">Claude Desktop, консольный клиент через API и свой \
Telegram-бот подключаются локально: команды и конфиг лежат \
<a href="$repo_url#запустить-у-себя">в README</a>.</p>

<h2>В новом чате отправьте запрос</h2>
<div class="box">
<pre id="request">$chat_request</pre>
<button type="button" data-copy="request">Скопировать</button>
</div>

<h2>Если сервера нет в списке инструментов</h2>
<p>Это запасной путь для помощника с доступом в сеть: он обращается \
к серверу напрямую.</p>
<div class="box">
<pre id="fallback">$fallback</pre>
<button type="button" data-copy="fallback">Скопировать</button>
</div>

<h2>Или напишите боту в Telegram</h2>
<p>Пришлите боту <a href="$bot_url">@$bot_name</a> файл CSV или Excel, \
запрос напишите в подписи к файлу. Примерно через минуту придут альбом \
графиков, текст выводов и отчёт в PDF.</p>

<h2>Какие инструменты видит модель</h2>
<p>Порядок этапов задаёт сервер: каждый ответ инструмента называет \
следующий шаг.</p>
<ul class="tools">
$tools
</ul>

<h2>Что стоит знать заранее</h2>
<p>У адреса нет входа: это демо-режим для показа. Память сервера общая \
для всех, кто подключился, а бот отправляет файл и запрос провайдеру \
языковой модели. Закрытые данные присылать не стоит.</p>

<footer>
<p>Код, README и примеры отчётов лежат в репозитории \
<a href="$repo_url">$repo_name</a>.</p>
</footer>
</main>
<script>
function copyByCommand(text) {
  var area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  var done = document.execCommand("copy");
  document.body.removeChild(area);
  return done ? Promise.resolve() : Promise.reject();
}
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).catch(function () {
      return copyByCommand(text);
    });
  }
  return copyByCommand(text);
}
document.querySelectorAll("button[data-copy]").forEach(function (button) {
  var label = button.textContent;
  button.addEventListener("click", function () {
    var text = document.getElementById(button.dataset.copy).textContent;
    copyText(text).then(function () {
      button.textContent = "Скопировано";
    }, function () {
      button.textContent = "Не получилось";
    }).then(function () {
      setTimeout(function () { button.textContent = label; }, 1600);
    });
  });
});
</script>
</body>
</html>
""")


def first_sentence(description: str) -> str:
    """Возвращает первую фразу описания инструмента одной строкой.

    Описание в схеме многострочное: первая фраза говорит, что инструмент
    делает, дальше идут подсказки для модели, которые странице не нужны.
    """
    paragraph = " ".join(description.split("\n\n")[0].split())
    return re.split(r"(?<=[.!?])\s", paragraph, maxsplit=1)[0]


def render_tools(tools: list[dict]) -> str:
    """Собирает пункты списка: имя, русское название, первая фраза."""
    items = []
    for tool in tools:
        items.append(
            f"<li><code>{html.escape(tool['name'])}</code>"
            f"<span>{html.escape(tool['title'])}</span>"
            f"<p>{html.escape(first_sentence(tool['description']))}</p></li>")
    return "\n".join(items)


def build_page(schema: dict) -> str:
    """Возвращает текст страницы для спецификации сервера ``schema``."""
    return PAGE.substitute(
        server_url=html.escape(SERVER_URL),
        bot_url=html.escape(BOT_URL),
        bot_name=html.escape(BOT_URL.rsplit("/", 1)[-1]),
        repo_url=html.escape(REPO_URL),
        repo_name=html.escape(REPO_URL.split("//", 1)[-1]),
        example_report=html.escape(EXAMPLE_REPORT),
        config=html.escape(CONFIG),
        chat_request=html.escape(CHAT_REQUEST),
        fallback=html.escape(FALLBACK),
        tools=render_tools(schema["tools"]),
        green=style.GREEN,
        dark_green=style.DARK_GREEN,
        text=style.TEXT,
        grey=style.GREY,
        light_grey=style.LIGHT_GREY,
        light_surface=LIGHT_SURFACE,
        dark_background=DARK_BACKGROUND,
        dark_surface=DARK_SURFACE,
        dark_text=DARK_TEXT,
        dark_muted=DARK_MUTED,
        dark_line=DARK_LINE,
    )


def main() -> None:
    """Пишет страницу в файл и печатает, сколько инструментов на ней."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    PAGE_PATH.write_text(build_page(schema), encoding="utf-8")
    print(f"{PAGE_PATH.relative_to(ROOT)}: инструментов на странице "
          f"{len(schema['tools'])}")


if __name__ == "__main__":
    main()
