"""Точка входа аналитического MCP-сервера.

Один и тот же сервер запускается двумя способами:

    python server.py                  # stdio: Claude Desktop, свой клиент
    python server.py --http           # Streamable HTTP: claude.ai

Скиллы и инструменты в обоих случаях одни и те же, меняется только способ
доставки сообщений.
"""

import argparse
import logging
import os

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response

from analytics_mcp.app import build_server
from analytics_mcp.settings import Settings


def add_report_route(server: MCPServer, settings: Settings) -> None:
    """Добавляет адрес, по которому браузер получает PDF отчёта.

    Ссылку с ключом выдаёт save_report. Без верного ключа сервер отвечает
    404, список отчётов нигде не показывается.
    """
    @server.custom_route("/reports/{key}/report.pdf", methods=["GET"])
    async def report(request: Request) -> Response:
        """Отдаёт PDF по ключу из адреса или отвечает 404."""
        path = settings.report_links.get(request.path_params["key"])
        if path is None:
            return PlainTextResponse("Отчёт не найден", status_code=404)
        return FileResponse(path, media_type="application/pdf")


def main() -> None:
    """Разбирает аргументы и запускает сервер в нужном режиме."""
    parser = argparse.ArgumentParser(
        description="MCP-сервер для анализа таблиц CSV и Excel")
    parser.add_argument("--http", action="store_true",
                        help="Streamable HTTP вместо stdio")
    parser.add_argument("--port", type=int, default=8000,
                        help="порт для режима HTTP (по умолчанию 8000)")
    parser.add_argument("--data-only", action="store_true",
                        help="читать файлы только из папки data/. Нужен, "
                             "когда запросы пишет посторонний человек, "
                             "например пользователь бота. В режиме HTTP "
                             "включён всегда")
    parser.add_argument("--public-host", default="",
                        help="имя хоста туннеля без https://, например "
                             "abc.trycloudflare.com")
    args = parser.parse_args()

    # В режиме stdio стандартный вывод занят протоколом, журнал идёт в stderr.
    logging.basicConfig(level=logging.INFO)

    if not args.http:
        # Локально сервер может сам открыть готовый отчёт на экране.
        open_report = os.environ.get("ANALYTICS_OPEN_REPORT") == "1"
        build_server(Settings(open_report=open_report,
                              restrict_to_data_dir=args.data_only)).run()
        return

    # По HTTP адрес сервера публичный, поэтому он читает только папку data/.
    # Отчёт лежит на диске сервера, пользователь получает его по ссылке.
    public_url = (f"https://{args.public_host}" if args.public_host
                  else f"http://127.0.0.1:{args.port}")
    settings = Settings(restrict_to_data_dir=True, public_url=public_url)
    server = build_server(settings)
    add_report_route(server, settings)
    # Без списка разрешённых хостов сервер отвечает 421 на запрос через
    # туннель: это защита от подмены DNS.
    hosts = [f"127.0.0.1:{args.port}", f"localhost:{args.port}"]
    if args.public_host:
        hosts += [args.public_host, f"{args.public_host}:*"]
    server.run(
        transport="streamable-http",
        port=args.port,
        json_response=True,  # быстрый туннель Cloudflare не пропускает SSE
        stateless_http=True,
        transport_security=TransportSecuritySettings(allowed_hosts=hosts),
    )


if __name__ == "__main__":
    main()
