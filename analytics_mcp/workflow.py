"""Порядок шагов анализа.

Порядок хранится в сервере и нигде больше. Он собирается из скиллов: у
каждого есть номер этапа, и каждый умеет ответить, выполнен ли его этап и
что вызвать дальше. Отсюда порядок попадает к модели тремя путями:

* ``instructions`` сервера — клиент получает их при подключении;
* промпт «Проанализировать файл» — пользователь выбирает его в клиенте;
* поле ``next_step`` в ответе каждого инструмента.

Третий путь нужен потому, что не каждый клиент выполняет ``instructions``.
"""

from typing import TYPE_CHECKING

from analytics_mcp.store import Analysis

if TYPE_CHECKING:
    from analytics_mcp.registry import Skill

FINISHED = ("Анализ завершён. Покажите пользователю выводы, рекомендации "
            "и путь к файлу отчёта.")


class Workflow:
    """Собирает порядок шагов из зарегистрированных скиллов."""

    def __init__(self) -> None:
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
        lines += [
            "",
            "Правила:",
            "- Проходи этапы по порядку. В каждом ответе инструмента есть "
            "поле next_step: выполняй его, пока анализ не завершён.",
            "- Таблица адресуется по dataset_id из ответа load_data. После "
            "очистки работай с новым dataset_id из ответа clean_data.",
            "- Цифры для выводов бери только из ответов инструментов, сам "
            "не считай.",
            "- Если пользователь прикрепил таблицу к чату и пути к файлу "
            "нет, передай её текст в аргументе csv_text инструмента "
            "load_data.",
            "- Отвечай на языке пользователя.",
        ]
        return "\n".join(lines)

    def prompt(self, file_path: str) -> str:
        """Собирает текст запроса на полный анализ одного файла."""
        steps = "; ".join(skill.title.lower() for skill in self.skills)
        return (
            f"Проанализируй файл {file_path}. Пройди все этапы по порядку "
            f"({steps}) и следуй полю next_step в ответах инструментов. "
            "В конце покажи ключевые выводы, практические рекомендации и "
            "путь к файлу отчёта."
        )
