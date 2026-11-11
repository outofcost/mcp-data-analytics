"""Порядок шагов анализа.

Порядок хранится в сервере и нигде больше. Он собирается из скиллов: у
каждого есть номер этапа, и каждый умеет ответить, выполнен ли его этап и
что вызвать дальше. Отсюда порядок попадает к модели тремя путями:

* ``instructions`` сервера: клиент получает их при подключении;
* промпт «Проанализировать файл»: пользователь выбирает его в клиенте;
* поле ``next_step`` в ответе каждого инструмента.

Третий путь нужен потому, что не каждый клиент выполняет ``instructions``.
"""

from typing import TYPE_CHECKING

from analytics_mcp.store import Analysis

if TYPE_CHECKING:
    from analytics_mcp.registry import Skill

FINISHED = ("Анализ завершён. Покажите пользователю без изменений текст "
            "из поля chat_summary ответа save_report: в нём выводы, "
            "рекомендации и где взять отчёт.")


class Workflow:
    """Собирает порядок шагов из зарегистрированных скиллов."""

    def __init__(self) -> None:
        """Начинает с пустого списка: скиллы добавляет сборка сервера."""
        self.skills: list["Skill"] = []

    def next_step(self, analysis: Analysis) -> str:
        """Возвращает подсказку первого невыполненного этапа."""
        for skill in self.skills:
            if not skill.is_done(analysis):
                return f"Этап «{skill.title}». {skill.hint(analysis)}"
        return FINISHED

    def instructions(self) -> str:
        """Собирает текст для поля ``instructions`` сервера."""
        lines = [
            "Сервер анализирует таблицы (CSV и Excel): загружает, чистит, "
            "строит графики и собирает отчёт. Анализ идёт по этапам:",
            "",
        ]
        for number, skill in enumerate(self.skills, start=1):
            names = ", ".join(method.__name__ for method in skill.tools())
            lines.append(f"{number}. {skill.title} ({type(skill).__name__}): "
                         f"{names}. {skill.guide}")
        # Общие правила лежат здесь, правила про конкретные инструменты
        # приносят сами скиллы.
        lines += [
            "",
            "Правила:",
            "- Проходи этапы по порядку. В каждом ответе инструмента есть "
            "поле next_step: выполняй его, пока анализ не завершён.",
            "- Цифры для выводов бери только из ответов инструментов, сам "
            "не считай.",
        ]
        lines += [f"- {rule}" for skill in self.skills
                  for rule in skill.rules]
        lines.append("- Отвечай на языке пользователя.")
        return "\n".join(lines)

    def prompt(self, file_path: str) -> str:
        """Собирает текст запроса на полный анализ одного файла."""
        steps = "; ".join(skill.title.lower() for skill in self.skills)
        return (
            f"Проанализируй файл {file_path} инструментами сервера "
            f"analytics. Начни с load_data(file_path=\"{file_path}\"), "
            f"пройди все этапы по порядку ({steps}) и следуй полю "
            "next_step в ответах инструментов. "
            "В конце покажи без изменений текст из поля chat_summary "
            "ответа save_report: в нём ключевые выводы, практические "
            "рекомендации и путь к файлу отчёта."
        )
