"""Консольный клиент: MCP-сервер анализа данных плюс модель через OpenRouter.

Клиент запускает MCP-сервер по stdio, берёт у него инструкции и список
инструментов и передаёт их модели. Модель решает, какой инструмент вызвать,
клиент выполняет вызов на сервере и возвращает ей результат. Своего промпта
с порядком шагов у клиента нет: порядок приходит от сервера.

Запуск из корня репозитория:
    python clients/console_client.py --file data/sales_data.csv \
        "Проанализируй продажи"

Ключ и модель читаются из файла .env: OPENROUTER_API_KEY, OPENROUTER_MODEL.
Адрес OPENROUTER_BASE_URL можно заменить на любой API в формате OpenAI.
"""

import argparse
import asyncio
import base64
import json
import os
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx2
from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, ImageContent, TextContent, Tool

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVER = ["python", "server.py"]
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
MAX_STEPS = 20          # предел запросов к модели за один анализ
RETRIES = 2             # повторов запроса при временном отказе провайдера
RETRY_PAUSE = 5         # секунд между повторами
PREVIEW_CHARS = 300     # сколько символов ответа инструмента идёт в журнал
REPORT_FILE = re.compile(r"[^\s\"'«»()]+\.(?:md|pdf|html)\b")


@dataclass
class AnalysisResult:
    """Итог одного анализа: ответ модели и файлы, сохранённые на диск."""

    answer: str                 # итоговый текст модели
    status: str                 # "ok" или "limit" (сработал предел шагов)
    steps: int                  # сколько запросов к модели ушло
    output_dir: Path            # папка с результатами
    log_path: Path              # журнал вызовов
    answer_path: Path           # итоговый текст модели в файле
    images: list[Path] = field(default_factory=list)   # графики
    files: list[Path] = field(default_factory=list)    # отчёты сервера


def load_env(path: Path = REPO_ROOT / ".env") -> None:
    """Читает строки КЛЮЧ=значение из .env в переменные окружения.

    Переменную, которая уже задана в окружении, не меняет.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def tools_to_openai(tools: list[Tool]) -> list[dict]:
    """Переводит инструменты MCP в формат function calling.

    Имя, описание и схема аргументов переходят без изменений.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def result_to_text(result: CallToolResult, tool_name: str, output_dir: Path,
                   images: list[Path]) -> str:
    """Собирает из ответа инструмента текст для модели.

    Картинку сохраняет в папку вывода и заменяет строкой с именем файла.
    Ответ с признаком is_error помечает как ошибку.
    """
    parts = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            extension = block.mime_type.split("/")[-1]
            number = len(images) + 1
            path = output_dir / f"chart_{number:02d}_{tool_name}.{extension}"
            path.write_bytes(base64.b64decode(block.data))
            images.append(path)
            parts.append(f"[картинка сохранена в файл {path.name}]")
        else:
            parts.append(f"[блок типа {block.type} пропущен]")
    text = "\n".join(parts)
    if result.is_error:
        text = f"ОШИБКА инструмента {tool_name}: исправь аргументы.\n{text}"
    return text


def find_report_files(text: str) -> list[Path]:
    """Ищет в ответе инструмента пути к отчётам (.md, .pdf, .html).

    Возвращает только файлы, которые существуют на диске. Относительный путь
    считает от корня репозитория: там запущен сервер.
    """
    found = []
    for match in REPORT_FILE.findall(text):
        path = Path(match)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_file() and path not in found:
            found.append(path)
    return found


def error_text(error: BaseException) -> str:
    """Возвращает текст ошибки одной строкой, в том числе для группы ошибок.

    Сбой запуска сервера приходит группой вложенных исключений: функция
    достаёт из неё исходные причины.
    """
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(error_text(inner) for inner in error.exceptions)
    return str(error) or type(error).__name__


def write_log(log_path: Path, record: dict) -> None:
    """Дописывает в журнал одну запись: строку JSON."""
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


async def ask_model(http: httpx2.AsyncClient, model: str, messages: list[dict],
                    tools: list[dict]) -> dict:
    """Отправляет диалог и инструменты модели, возвращает разобранный ответ.

    Временный отказ провайдера (429 и ошибки 5xx) повторяет после паузы.
    Анализ это цепочка из десятка запросов, и без повтора один отказ
    срывал её целиком: так было на сравнении моделей.
    """
    for attempt in range(RETRIES + 1):
        response = await http.post(
            "/chat/completions",
            json={"model": model, "messages": messages, "tools": tools},
        )
        temporary = (response.status_code == 429
                     or response.status_code >= 500)
        if not temporary or attempt == RETRIES:
            break
        await asyncio.sleep(RETRY_PAUSE)
    if response.status_code != 200:
        raise RuntimeError(
            f"API модели ответил {response.status_code}: {response.text[:300]}"
        )
    data = response.json()
    if "error" in data or not data.get("choices"):
        raise RuntimeError(f"API модели вернул ошибку: {str(data)[:300]}")
    return data


async def call_tool(mcp_client: Client, call: dict, output_dir: Path,
                    images: list[Path]) -> tuple[dict, str, bool]:
    """Выполняет на сервере один вызов инструмента, который запросила модель.

    Возвращает аргументы, текст для модели и признак ошибки. Сбой разбора
    аргументов и отказ сервера тоже возвращает как ошибку: модель читает
    текст и может повторить вызов с исправленными аргументами.
    """
    name = call["function"]["name"]
    raw_arguments = call["function"].get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        text = f"ОШИБКА: аргументы {name} не разобраны как JSON ({error})."
        return {"raw": raw_arguments}, text, True
    try:
        result = await mcp_client.call_tool(name, arguments)
    except Exception as error:  # сервер отклонил вызов целиком
        text = f"ОШИБКА: сервер отклонил вызов {name}: {error_text(error)}"
        return arguments, text, True
    text = result_to_text(result, name, output_dir, images)
    return arguments, text, bool(result.is_error)


async def run_analysis(
    file_path: str | Path | None,
    request: str,
    *,
    server_command: list[str] | None = None,
    output_dir: str | Path | None = None,
    model: str | None = None,
    max_steps: int = MAX_STEPS,
    progress: Callable[[str], None] = print,
) -> AnalysisResult:
    """Проводит один анализ: файл и запрос на входе, ответ и файлы на выходе.

    Эту функцию вызывают и консоль, и Telegram-бот.

    Args:
        file_path: путь к CSV или Excel. None, если файл не нужен.
        request: запрос пользователя обычным текстом.
        server_command: команда запуска MCP-сервера, по умолчанию
            ``python server.py`` из корня репозитория.
        output_dir: папка для графиков, журнала и ответа. По умолчанию
            ``output/<дата_время>`` в корне репозитория.
        model: имя модели. По умолчанию OPENROUTER_MODEL из .env.
        max_steps: предел запросов к модели.
        progress: функция, которая получает строки о ходе работы.
    """
    load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Нет OPENROUTER_API_KEY. Скопируйте .env.example в .env "
            "и вставьте ключ."
        )
    model = model or os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(output_dir or REPO_ROOT / "output" / stamp)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "console-log.txt"

    # Сервер стартует тем же интерпретатором, что и клиент, из корня
    # репозитория. Ключ API в его окружение не попадает.
    command = list(server_command or DEFAULT_SERVER)
    if command[0] in ("python", "python3"):
        command[0] = sys.executable
    server = StdioServerParameters(
        command=command[0], args=command[1:], cwd=REPO_ROOT
    )

    user_text = request
    if file_path is not None:
        path = Path(file_path).resolve()
        if path.is_relative_to(REPO_ROOT):
            path = path.relative_to(REPO_ROOT)
        user_text = f"Файл с данными: {path}\n\n{request}"

    write_log(log_path, {
        "event": "start",
        "model": model,
        "server": " ".join([Path(command[0]).name, *command[1:]]),
        "request": user_text,
    })

    images: list[Path] = []
    files: list[Path] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
    status, answer, step = "limit", "", 0

    async with Client(server) as mcp_client, httpx2.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120,
    ) as http:
        tools = tools_to_openai((await mcp_client.list_tools()).tools)
        messages = [{"role": "user", "content": user_text}]
        if mcp_client.instructions:
            messages.insert(
                0, {"role": "system", "content": mcp_client.instructions}
            )

        for step in range(1, max_steps + 1):
            try:
                data = await ask_model(http, model, messages, tools)
            except Exception as error:
                write_log(log_path, {
                    "event": "end", "status": "error",
                    "error": error_text(error),
                })
                raise
            for key in usage:
                usage[key] += (data.get("usage") or {}).get(key) or 0
            message = data["choices"][0]["message"]
            messages.append(message)

            calls = message.get("tool_calls") or []
            if not calls:
                status, answer = "ok", message.get("content") or ""
                break

            for call in calls:
                arguments, text, is_error = await call_tool(
                    mcp_client, call, output_dir, images
                )
                files += [
                    path for path in find_report_files(text)
                    if path not in files
                ]
                name = call["function"]["name"]
                write_log(log_path, {
                    "event": "tool_call",
                    "step": step,
                    "tool": name,
                    "arguments": arguments,
                    "is_error": is_error,
                    "result": text[:PREVIEW_CHARS],
                })
                mark = "ОШИБКА" if is_error else "ок"
                progress(f"[шаг {step}] {name}({arguments}) → {mark}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": text,
                })

    if status == "limit":
        answer = (
            f"Остановился: достигнут предел шагов ({max_steps}), итогового "
            "ответа модель не дала. Журнал вызовов показывает, где она "
            "застряла."
        )
    answer_path = output_dir / "answer.md"
    answer_path.write_text(answer, encoding="utf-8")
    write_log(log_path, {
        "event": "end",
        "status": status,
        "steps": step,
        "images": [path.name for path in images],
        "usage": usage,
    })
    return AnalysisResult(
        answer=answer, status=status, steps=step, output_dir=output_dir,
        log_path=log_path, answer_path=answer_path, images=images, files=files,
    )


def main() -> None:
    """Разбирает аргументы командной строки и запускает один анализ."""
    parser = argparse.ArgumentParser(
        description="Анализ CSV или Excel через MCP-сервер и модель OpenRouter"
    )
    parser.add_argument("request", help="запрос обычным текстом")
    parser.add_argument("--file", help="путь к CSV или Excel")
    parser.add_argument("--server", default=None,
                        help='команда запуска сервера, по умолчанию '
                             '"python server.py"')
    parser.add_argument("--model", default=None,
                        help="модель OpenRouter, по умолчанию из .env")
    parser.add_argument("--out", default=None, help="папка для результатов")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS,
                        help="предел запросов к модели")
    args = parser.parse_args()

    try:
        result = asyncio.run(run_analysis(
            args.file,
            args.request,
            server_command=shlex.split(args.server) if args.server else None,
            output_dir=args.out,
            model=args.model,
            max_steps=args.max_steps,
        ))
    except Exception as error:
        sys.exit(
            f"Анализ не выполнен: {error_text(error)}\n"
            "Проверьте команду запуска сервера (--server) и ключ в .env."
        )

    print()
    print(result.answer)
    print()
    print(f"Шагов: {result.steps}, статус: {result.status}")
    print(f"Папка с результатами: {result.output_dir}")
    for path in [*result.images, *result.files]:
        print(f"  файл: {path.name}")
    print(f"  журнал вызовов: {result.log_path.name}")


if __name__ == "__main__":
    main()
