"""Выгружает спецификацию сервера в docs/tools-schema.json.

В файл попадает то, что видит MCP-клиент при подключении: инструкция
сервера, инструменты с входными и выходными схемами, промпты. Файл нужен,
чтобы посмотреть спецификацию, не запуская сервер.

Запуск из корня репозитория: ``python scripts/export_tools_schema.py``
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp import Client  # noqa: E402

from analytics_mcp.app import build_server  # noqa: E402


async def export() -> dict:
    """Подключается к серверу в памяти и собирает его спецификацию."""
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools
        prompts = (await client.list_prompts()).prompts
        return {
            "instructions": client.instructions,
            "tools": [tool.model_dump(mode="json", by_alias=True,
                                      exclude_none=True) for tool in tools],
            "prompts": [prompt.model_dump(mode="json", by_alias=True,
                                          exclude_none=True)
                        for prompt in prompts],
        }


def main() -> None:
    """Пишет спецификацию в файл и печатает список инструментов."""
    spec = asyncio.run(export())
    path = ROOT / "docs" / "tools-schema.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    names = ", ".join(tool["name"] for tool in spec["tools"])
    print(f"{path.relative_to(ROOT)}: {len(spec['tools'])} инструментов "
          f"({names})")


if __name__ == "__main__":
    main()
