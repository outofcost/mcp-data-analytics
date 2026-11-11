"""Общий ответ для инструментов с графиком.

Любой скилл, который рисует график, заканчивает одной функцией: она
сохраняет картинку, запоминает график для отчёта и собирает ответ из
текста и PNG. Так графики новых скиллов попадают в отчёт без правок ядра.
"""

from matplotlib.figure import Figure
from mcp.server.mcpserver import Image

from analytics_mcp import style
from analytics_mcp.models import ChartResult
from analytics_mcp.registry import Skill
from analytics_mcp.store import Chart, Dataset


def publish_chart(skill: Skill, dataset: Dataset, key: str, title: str,
                  figure: Figure, facts: list[str],
                  excluded: int) -> list[str | Image]:
    """Сохраняет график и возвращает ответ инструмента: текст и картинку.

    Args:
        skill: скилл, который построил график.
        dataset: таблица, по которой он построен.
        key: имя инструмента и его аргументы через двоеточие. Повторный
            вызов с тем же ключом заменяет прежний график.
        title: заголовок графика.
        figure: готовый график matplotlib.
        facts: что видно на графике, с числами.
        excluded: сколько строк с выбросами не вошло в расчёт.
    """
    analysis = dataset.analysis
    existing = next((c for c in analysis.charts if c.key == key), None)
    if existing:
        path = existing.path
        analysis.charts.remove(existing)
    else:
        number = len(analysis.charts) + 1
        folder = skill.settings.output_dir / analysis.root_id
        path = folder / f"chart_{number:02d}_{key.split(':')[0]}.png"
    png = style.save_figure(figure, path)
    analysis.charts.append(Chart(key, title, path, facts))
    result = ChartResult(
        dataset_id=dataset.dataset_id,
        title=title,
        file=skill.settings.relative(path),
        facts=facts,
        excluded_outliers=excluded,
        charts_built=len(analysis.charts),
        next_step=skill.next_step(dataset),
    )
    return [result.model_dump_json(indent=2), Image(data=png, format="png")]
