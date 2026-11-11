"""Реестр скиллов.

Скилл — это класс одного этапа анализа. Его методы, помеченные ``@tool``,
становятся инструментами MCP. Чтобы добавить скилл, достаточно положить
новый файл в папку ``skills/`` и пометить класс ``@register_skill``:
сервер сам найдёт файл, ядро менять не нужно.
"""

import importlib
import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from analytics_mcp.settings import Settings
from analytics_mcp.store import Analysis, Dataset, DatasetStore

if TYPE_CHECKING:
    from analytics_mcp.workflow import Workflow

_SKILLS: dict[str, type["Skill"]] = {}


def tool(method: Callable[..., Any]) -> Callable[..., Any]:
    """Помечает метод скилла как инструмент MCP."""
    method.is_tool = True
    return method


class Skill:
    """Базовый класс скилла: один этап анализа и его инструменты.

    Attributes:
        stage: номер этапа. Сервер сортирует скиллы по нему, так получается
            порядок шагов анализа.
        title: короткое название этапа.
        guide: что делает этап. Текст попадает в инструкцию сервера.
    """

    stage: int = 0
    title: str = ""
    guide: str = ""

    def __init__(self, store: DatasetStore, settings: Settings,
                 workflow: "Workflow") -> None:
        self.store = store
        self.settings = settings
        self.workflow = workflow

    def tools(self) -> list[Callable[..., Any]]:
        """Возвращает инструменты скилла в порядке объявления в классе."""
        names = [name for name, value in vars(type(self)).items()
                 if getattr(value, "is_tool", False)]
        return [getattr(self, name) for name in names]

    def is_done(self, analysis: Analysis) -> bool:
        """Отвечает, выполнен ли этап. По умолчанию этап необязательный."""
        return True

    def hint(self, analysis: Analysis) -> str:
        """Подсказывает модели, какой инструмент этапа вызвать дальше."""
        return ""

    def next_step(self, dataset: Dataset) -> str:
        """Возвращает подсказку следующего шага для ответа инструмента."""
        return self.workflow.next_step(dataset.analysis)


def register_skill(cls: type[Skill]) -> type[Skill]:
    """Добавляет класс скилла в реестр. Используется как декоратор."""
    _SKILLS[cls.__name__] = cls
    return cls


def discover_skills(
        package: str = "analytics_mcp.skills") -> list[type[Skill]]:
    """Импортирует все модули папки скиллов и возвращает их по этапам."""
    folder = importlib.import_module(package).__path__
    for module in pkgutil.iter_modules(folder):
        importlib.import_module(f"{package}.{module.name}")
    return sorted(_SKILLS.values(), key=lambda cls: cls.stage)
