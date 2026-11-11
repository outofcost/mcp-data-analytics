"""Telegram-бот: тот же анализ, что в консольном клиенте, из чата.

Пользователь присылает CSV или Excel и пишет запрос в подписи к файлу.
Бот сохраняет файл в data/uploads, вызывает run_analysis из консольного
клиента, отправляет графики альбомом и отчёт одним PDF. Следующее текстовое
сообщение задаёт новый запрос к последнему присланному файлу.

Бот сам опрашивает Telegram (long polling), публичный адрес ему не нужен.
Сообщения обрабатывает по одному: второй пользователь ждёт своей очереди.

Запуск из корня репозитория:
    python clients/telegram_bot.py

Из .env читаются TELEGRAM_BOT_TOKEN и необязательный список
TELEGRAM_ALLOWED_CHATS (номера чатов через запятую; пусто: бот отвечает всем).
"""

import argparse
import asyncio
import html
import json
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

import httpx2

from console_client import (DEFAULT_SERVER, REPO_ROOT, error_text, load_env,
                            run_analysis)

TELEGRAM_API = "https://api.telegram.org"
UPLOAD_DIR = REPO_ROOT / "data" / "uploads"
# Те же расширения, что читает сервер (analytics_mcp/skills/loading.py).
ALLOWED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}
# Запросы боту пишут посторонние люди, поэтому сервер под ним читает файлы
# только из своей папки data/: туда же бот кладёт присланные файлы.
BOT_SERVER = [*DEFAULT_SERVER, "--data-only"]
MAX_FILE_BYTES = 20 * 1024 * 1024   # файлы крупнее Bot API боту не отдаёт
MESSAGE_LIMIT = 4000                # предел Telegram: 4096 символов
POLL_SECONDS = 30                   # сколько Telegram держит запрос открытым
ALBUM_SIZE = 10                     # предел Telegram: 10 фото в альбоме
DEFAULT_REQUEST = "Проанализируй данные, построй графики и дай рекомендации"
# Таблица Markdown: строка-разделитель |---|---| и строка с ячейками.
TABLE_RULE = re.compile(r"^\|[ \t:|-]+\|[ \t]*\n?", re.MULTILINE)
TABLE_ROW = re.compile(r"^\|(.+)\|[ \t]*$", re.MULTILINE)
HELP = (
    "Пришлите файл CSV или Excel. Запрос напишите в подписи к файлу, "
    f"без подписи отправлю запрос «{DEFAULT_REQUEST}».\n\n"
    "В ответ придут графики, выводы и отчёт файлом. Анализ занимает "
    "несколько минут. Следующее текстовое сообщение задаст новый запрос "
    "к тому же файлу.\n\n"
    "Файл и запрос уходят провайдеру языковой модели через OpenRouter."
)


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Режет длинный текст на части по границам строк.

    Строку длиннее предела режет посередине: иначе Telegram её не примет.
    """
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        current += line
    parts.append(current)
    return [
        part[start:start + limit]
        for part in parts
        for start in range(0, len(part), limit)
    ]


def to_telegram_html(text: str) -> str:
    """Переводит разметку Markdown из ответа модели в HTML для Telegram.

    Заголовки (#) и жирный текст (**) становятся жирными. Имена в обратных
    кавычках идут моноширинным шрифтом: иначе Telegram превращает «report.md»
    в ссылку на сайт. Таблиц в Telegram нет, поэтому строка таблицы
    становится обычной строкой, ячейки разделяются точкой.
    """
    text = html.escape(text, quote=False)
    text = TABLE_RULE.sub("", text)
    text = TABLE_ROW.sub(
        lambda match: " · ".join(
            cell.strip() for cell in match.group(1).split("|")
        ),
        text,
    )
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(
        r"^#{1,6} +(.+)$",
        lambda match: "**" + match.group(1).replace("**", "") + "**",
        text,
        flags=re.MULTILINE,
    )
    return re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)


class TelegramBot:
    """Бот: принимает файл и запрос, возвращает графики и отчёт."""

    def __init__(self, token: str, server_command: list[str] | None = None,
                 allowed_chats: set[int] | None = None) -> None:
        """Запоминает токен, команду запуска MCP-сервера и список чатов."""
        self.token = token
        self.server_command = server_command or BOT_SERVER
        self.allowed_chats = allowed_chats or set()
        self.last_file: dict[int, Path] = {}   # чат → последний файл
        self.http = httpx2.AsyncClient(
            base_url=f"{TELEGRAM_API}/bot{token}", timeout=60
        )

    def hide_token(self, text: str) -> str:
        """Убирает токен из текста перед печатью или отправкой."""
        return text.replace(self.token, "<токен>")

    async def api(self, method: str, data: dict | None = None,
                  files: dict | None = None, timeout: float = 60):
        """Вызывает метод Bot API и возвращает поле result из ответа."""
        try:
            response = await self.http.post(
                f"/{method}", data=data, files=files, timeout=timeout
            )
        except httpx2.HTTPError as error:
            # Адрес запроса содержит токен, поэтому исходную ошибку не
            # показываю, оставляю только её тип.
            raise RuntimeError(
                f"Telegram недоступен ({type(error).__name__})"
            ) from None
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(
                f"Telegram отклонил {method}: {body.get('description')}"
            )
        return body["result"]

    async def send_text(self, chat_id: int, text: str,
                        markdown: bool = False) -> None:
        """Отправляет текст, длинный режет на части по пределу Telegram.

        С markdown=True переводит разметку модели в оформление Telegram.
        Если Telegram не принял оформление, отправляет ту же часть простым
        текстом.
        """
        for part in split_text(text):
            if markdown:
                try:
                    await self.api("sendMessage", {
                        "chat_id": chat_id,
                        "text": to_telegram_html(part),
                        "parse_mode": "HTML",
                    })
                    continue
                except RuntimeError as error:
                    print(f"Оформление не принято, шлю текстом: {error}")
            await self.api("sendMessage", {"chat_id": chat_id, "text": part})

    async def send_file(self, chat_id: int, path: Path,
                        as_photo: bool = False) -> None:
        """Отправляет файл документом или картинкой.

        Картинку, которую Telegram не принял как фото, отправляет документом.
        """
        content = (path.name, path.read_bytes())
        if as_photo:
            try:
                await self.api("sendPhoto", {"chat_id": chat_id},
                               files={"photo": content})
                return
            except RuntimeError as error:
                print(f"Фото {path.name} не ушло, шлю документом: {error}")
        await self.api("sendDocument", {"chat_id": chat_id},
                       files={"document": content})

    async def send_album(self, chat_id: int, images: list[Path]) -> None:
        """Отправляет графики одним сообщением-альбомом.

        В альбом Telegram входит от 2 до 10 фото, поэтому длинный список
        делится на несколько альбомов, а один график уходит обычным фото.
        Если Telegram альбом не принял, графики уходят по одному.
        """
        for start in range(0, len(images), ALBUM_SIZE):
            group = images[start:start + ALBUM_SIZE]
            if len(group) > 1:
                media = [{"type": "photo", "media": f"attach://photo{n}"}
                         for n in range(len(group))]
                files = {f"photo{n}": (path.name, path.read_bytes())
                         for n, path in enumerate(group)}
                try:
                    await self.api(
                        "sendMediaGroup",
                        {"chat_id": chat_id, "media": json.dumps(media)},
                        files=files,
                    )
                    continue
                except RuntimeError as error:
                    print(f"Альбом не ушёл, шлю графики по одному: {error}")
            for path in group:
                await self.send_file(chat_id, path, as_photo=True)

    async def download(self, document: dict) -> Path:
        """Скачивает присланный файл в data/uploads и возвращает путь.

        Проверяет расширение и размер. При отказе бросает ValueError
        с текстом для пользователя.
        """
        name = Path(document.get("file_name") or "file").name
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Файл «{name}» не подходит. Пришлите CSV или Excel "
                "(.csv, .tsv, .txt, .xlsx, .xlsm)."
            )
        if document.get("file_size", 0) > MAX_FILE_BYTES:
            raise ValueError(
                f"Файл «{name}» больше 20 МБ, Telegram не отдаёт такие "
                "файлы боту. Пришлите файл меньше."
            )
        info = await self.api("getFile", {"file_id": document["file_id"]})
        try:
            response = await self.http.get(
                f"{TELEGRAM_API}/file/bot{self.token}/{info['file_path']}"
            )
        except httpx2.HTTPError as error:
            raise RuntimeError(
                f"Файл не скачался ({type(error).__name__})"
            ) from None
        if response.status_code != 200:
            raise RuntimeError(f"Файл не скачался: {response.status_code}")

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = re.sub(r"[^\w.\-]", "_", name)
        path = UPLOAD_DIR / f"{stamp}_{safe_name}"
        path.write_bytes(response.content)
        return path

    async def handle(self, message: dict) -> None:
        """Обрабатывает одно сообщение: команду, файл или текстовый запрос."""
        chat_id = message["chat"]["id"]
        if self.allowed_chats and chat_id not in self.allowed_chats:
            await self.send_text(chat_id, "Бот закрыт для этого чата.")
            return
        text = (message.get("caption") or message.get("text") or "").strip()
        if text.startswith("/"):    # /start, /help и любая другая команда
            await self.send_text(chat_id, HELP)
            return

        document = message.get("document")
        if document:
            try:
                self.last_file[chat_id] = await self.download(document)
            except ValueError as error:
                await self.send_text(chat_id, str(error))
                return
        file_path = self.last_file.get(chat_id)
        if file_path is None:
            await self.send_text(chat_id, HELP)
            return

        request = text or DEFAULT_REQUEST
        await self.send_text(
            chat_id,
            f"Принял файл «{file_path.name}». Запрос: «{request}». "
            "Анализ занимает несколько минут.",
        )
        result = await run_analysis(
            file_path, request, server_command=self.server_command
        )
        await self.send_album(chat_id, result.images)
        await self.send_text(
            chat_id, result.answer or "Модель не ответила.", markdown=True
        )
        # Отчёт сервера уходит одним файлом PDF: графики у него внутри.
        # Если PDF нет, уходят остальные файлы отчёта, а без них итоговый
        # текст модели.
        reports = ([path for path in result.files if path.suffix == ".pdf"]
                   or result.files or [result.answer_path])
        for path in reports:
            await self.send_file(chat_id, path)

    async def run(self) -> None:
        """Опрашивает Telegram и передаёт каждое сообщение в handle."""
        me = await self.api("getMe")
        print(f"Бот @{me['username']} запущен. Остановка: Ctrl+C.")
        offset = 0
        while True:
            try:
                updates = await self.api(
                    "getUpdates",
                    {"offset": offset, "timeout": POLL_SECONDS,
                     "allowed_updates": '["message"]'},
                    timeout=POLL_SECONDS + 10,
                )
            except RuntimeError as error:
                print(f"Опрос не удался, повторю через 5 секунд: {error}")
                await asyncio.sleep(5)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue
                try:
                    await self.handle(message)
                except Exception as error:
                    problem = self.hide_token(error_text(error))
                    print(f"Сообщение не обработано: {problem}")
                    try:
                        await self.send_text(
                            message["chat"]["id"],
                            f"Анализ не выполнен: {problem}",
                        )
                    except RuntimeError:
                        pass    # Telegram недоступен, сообщить некуда


def main() -> None:
    """Читает настройки из .env и запускает бота."""
    parser = argparse.ArgumentParser(
        description="Telegram-бот для анализа CSV и Excel через MCP-сервер"
    )
    parser.add_argument("--server", default=None,
                        help='команда запуска сервера, по умолчанию '
                             '"python server.py --data-only"')
    args = parser.parse_args()

    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit(
            "Нет TELEGRAM_BOT_TOKEN. Получите токен у @BotFather "
            "и добавьте его в .env."
        )
    chats = os.environ.get("TELEGRAM_ALLOWED_CHATS", "")
    bot = TelegramBot(
        token,
        server_command=shlex.split(args.server) if args.server else None,
        allowed_chats={int(chat) for chat in chats.split(",") if chat.strip()},
    )
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("Бот остановлен.")


if __name__ == "__main__":
    main()
