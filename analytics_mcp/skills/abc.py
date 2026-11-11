"""Скилл ABC-анализа: какие значения категории дают основной результат.

Этот файл добавлен после готового ядра как пример расширения. Чтобы скилл
заработал, не пришлось менять ни один другой файл: сервер сам нашёл модуль
в папке ``skills/``, зарегистрировал инструмент и вписал этап в инструкцию.
График скилла попадает в отчёт наравне с остальными.
"""

from typing import Annotated

from matplotlib.ticker import FuncFormatter
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from analytics_mcp import columns as cols
from analytics_mcp import style
from analytics_mcp.charts import publish_chart
from analytics_mcp.registry import Skill, register_skill, tool
from analytics_mcp.style import column_label, column_title, format_number

# Границы групп по накопленной доле: A даёт первые 80% суммы, B следующие
# 15%, C оставшиеся 5%.
A_SHARE = 0.80
B_SHARE = 0.95
GROUP_COLORS = {"A": style.DARK_GREEN, "B": style.GREEN, "C": style.GREY}
MAX_BARS = 20


@register_skill
class AbcAnalysisSkill(Skill):
    """Необязательный этап между графиками и выводами: ABC-анализ."""

    stage = 35
    title = "ABC-анализ"
    guide = ("Необязательный этап. Делит значения категории на группы A, B "
             "и C по вкладу в показатель. Вызывайте, когда пользователь "
             "спрашивает, какие товары, регионы или клиенты главные.")

    @tool
    def abc_analysis(
        self,
        dataset_id: Annotated[str, Field(
            description="Идентификатор таблицы. После очистки: из ответа "
                        "clean_data")],
        col: Annotated[str, Field(
            description="Колонка-категория, значения которой делятся на "
                        "группы: товар, регион, клиент")],
        value_col: Annotated[str, Field(
            description="Числовая колонка, по сумме которой считается "
                        "вклад. Пусто: главный показатель таблицы")] = "",
    ) -> list[str | Image]:
        """Делит значения категории на группы A, B, C по вкладу в сумму.

        Значения сортируются по убыванию суммы. Группа A даёт первые 80%
        суммы, B следующие 15%, C оставшиеся 5%. Возвращает текст (состав
        групп с долями) и диаграмму Парето в формате PNG.
        """
        dataset = self.store.get(dataset_id)
        roles = dataset.roles
        categories = cols.columns_with_role(roles, cols.CATEGORY)
        numbers = cols.columns_with_role(roles, cols.NUMBER)
        if roles.get(col) != cols.CATEGORY:
            raise ToolError(
                f"Для аргумента col нужна колонка-категория, «{col}» не "
                f"подходит. Подходят: {', '.join(categories) or 'нет'}.")
        value_col = value_col or cols.pick_measure(roles) or ""
        if roles.get(value_col) != cols.NUMBER:
            raise ToolError(
                f"Для аргумента value_col нужна числовая колонка, "
                f"«{value_col}» не подходит. Подходят: "
                f"{', '.join(numbers) or 'нет'}.")

        frame, excluded = dataset.working_frame()
        totals = frame.groupby(col)[value_col].sum().sort_values(
            ascending=False)
        negative = totals[totals < 0]
        if len(negative) or totals.sum() <= 0:
            raise ToolError(
                "ABC-анализ считается по неотрицательным суммам, а в "
                f"колонке «{value_col}» есть отрицательные: "
                f"{', '.join(str(v) for v in negative.index) or 'итог'}. "
                "Возьмите другой показатель, например выручку.")

        share = totals / totals.sum()
        before = share.cumsum() - share  # накопленная доля до значения
        groups = before.map(lambda part: "A" if part < A_SHARE
                            else "B" if part < B_SHARE else "C")

        shown = totals.head(MAX_BARS)
        scale, scale_word = style.pick_scale(shown.max())
        title = (f"ABC-анализ: {column_title(value_col)} по колонке "
                 f"«{column_title(col)}»")
        figure, axes = style.new_figure(title)
        axes.bar([str(v) for v in shown.index], shown / scale,
                 color=[GROUP_COLORS[groups[v]] for v in shown.index])
        axes.set_ylabel(column_label(value_col, scale_word),
                        color=style.TEXT)
        axes.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _: format_number(value)))
        axes.tick_params(axis="x", rotation=30)
        line = axes.twinx()
        line.plot(range(len(shown)), 100 * share.cumsum().head(MAX_BARS),
                  color=style.TEXT, marker="o", markersize=4, linewidth=1.5)
        line.set_ylim(0, 105)
        line.set_ylabel("Накопленная доля, %", color=style.TEXT)
        line.spines[["top"]].set_visible(False)
        for name in sorted(set(groups[shown.index])):
            axes.bar(0, 0, color=GROUP_COLORS[name], label=f"Группа {name}")
        axes.legend(frameon=False, fontsize=9, ncol=3, loc="upper center",
                    bbox_to_anchor=(0.5, -0.25))

        facts = [f"Значений в колонке «{col}»: {len(totals)}."]
        for name in "ABC":
            members = groups[groups == name].index
            if len(members):
                part = f"{100 * share[members].sum():.1f}%".replace(".", ",")
                facts.append(
                    f"Группа {name} ({len(members)} знач., {part} суммы): "
                    + ", ".join(str(v) for v in members[:10])
                    + (" и другие." if len(members) > 10 else "."))
        key = f"abc_analysis:{col}:{value_col}"
        return publish_chart(self, dataset, key, title, figure, facts,
                             excluded)
