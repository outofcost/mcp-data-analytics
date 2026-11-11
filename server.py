"""Точка входа аналитического MCP-сервера.

Один и тот же сервер запускается двумя способами:

    python server.py                  # stdio: Claude Desktop, свой клиент
    python server.py --http           # Streamable HTTP: claude.ai, ChatGPT

Скиллы и инструменты в обоих случаях одни и те же, меняется только способ
доставки сообщений.
"""

import argparse
import logging

from mcp.server.transport_security import TransportSecuritySettings

from analytics_mcp.app import build_server
from analytics_mcp.settings import Settings


def main() -> None:
    """Разбирает аргументы и запускает сервер в нужном режиме."""
    parser = argparse.ArgumentParser(
        description="MCP-сервер для анализа таблиц CSV и Excel")
    parser.add_argument("--http", action="store_true",
                        help="Streamable HTTP вместо stdio")
    parser.add_argument("--port", type=int, default=8000,
                        help="порт для режима HTTP (по умолчанию 8000)")
    parser.add_argument("--public-host", default="",
                        help="имя хоста туннеля без https://, например "
                             "abc.trycloudflare.com")
    args = parser.parse_args()

    # В режиме stdio стандартный вывод занят протоколом, журнал идёт в stderr.
    logging.basicConfig(level=logging.INFO)

    if not args.http:
        build_server().run()
        return

    # По HTTP адрес сервера публичный, поэтому он читает только папку data/.
    server = build_server(Settings(restrict_to_data_dir=True))
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
