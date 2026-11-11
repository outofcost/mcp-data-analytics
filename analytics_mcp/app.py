"""Сборка MCP-сервера из скиллов.

Здесь нет ни одного имени скилла или инструмента: сервер берёт их из
реестра. Поэтому новый скилл не требует правок в этом файле.
"""

from mcp.server import MCPServer
from mcp.server.mcpserver.prompts.base import Prompt

from analytics_mcp.registry import discover_skills
from analytics_mcp.settings import Settings
from analytics_mcp.store import DatasetStore
from analytics_mcp.workflow import Workflow

SERVER_NAME = "analytics"


def build_server(settings: Settings | None = None) -> MCPServer:
    """Создаёт сервер: находит скиллы и регистрирует их инструменты."""
    settings = settings or Settings()
    # Сервер, доступный снаружи, выдаёт таблицам неугадываемые имена.
    store = DatasetStore(private_ids=settings.restrict_to_data_dir)
    workflow = Workflow()
    workflow.skills = [skill_class(store, settings, workflow)
                       for skill_class in discover_skills()]

    server = MCPServer(SERVER_NAME, instructions=workflow.instructions())
    for skill in workflow.skills:
        for method in skill.tools():
            server.add_tool(method, title=method.title or None,
                            description=skill.describe(method))

    def analyze_file(file_path: str) -> str:
        """Полный анализ файла: загрузка, очистка, графики, отчёт."""
        return workflow.prompt(file_path)

    server.add_prompt(Prompt.from_function(
        analyze_file, title="Проанализировать файл"))
    return server
