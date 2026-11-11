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

# Границы групп по накопленной доле. Значение идёт в группу A, пока сумма
# значений до него меньше 80% итога, в группу B, пока она меньше 95%.
A_SHARE = 0.80
B_SHARE = 0.95
GROUP_COLORS = {"A": style.DARK_GREEN, "B": style.GREEN, "C": style.GREY}
MAX_BARS = 20       # столько самых крупных значений помещается на графике
LABEL_CHARS = 18    # длинное название товара на оси обрезается


@register_skill
class AbcAnalysisSkill(Skill):
    """Необязательный этап между графиками и выводами: ABC-анализ."""

    stage = 35
    title = "ABC-анализ"
    guide = ("Необязательный этап. Делит значения категории на группы A, B "
             "и C по вкладу в показатель. Вызывайте, когда пользователь "
             "спрашивает, какие товары, регионы или клиенты главные.")

    @tool(title="ABC-анализ")
    def abc_analysis(
        self,
        dataset_id: Annotated[str, Field(
            description="Идентификатор таблицы. После очистки: из ответа "
                        "clean_data")],
        col: Annotated[str, Field(
            description="Колонка, значения которой делятся на группы: "
                        "товар, регион, клиент. Значения в ней должны "
                        "повторяться")],
        value_col: Annotated[str, Field(
            description="Числовая колонка, по сумме которой считается "
                        "вклад. Пусто: главный показатель таблицы")] = "",
    ) -> list[str | Image]:
        """Делит значения колонки на группы A, B, C по вкладу в сумму.

        Значения сортируются по убыванию суммы. Значение попадает в группу
        A, пока сумма значений до него меньше 80% итога, в группу B, пока
        она меньше 95%, остальные идут в C. Поэтому при малом числе
        значений группа A может дать больше 80%. Подходит и колонка
        с большим числом значений (сотни товаров): на графике будут 20
        самых крупных. Возвращает текст (состав групп с долями) и диаграмму
        Парето в формате PNG.
        """
        dataset = self.store.current(dataset_id)
        roles = dataset.roles
        # Подходит категория и текстовая колонка с повторами. Товаров
        # в настоящем ассортименте сотни, роль у такой колонки «текст».
        frame = dataset.frame
        suitable = [
            name for name, role in roles.items()
            if role == cols.CATEGORY or (
                role == cols.TEXT
                and frame[name].nunique() < frame[name].count())
        ]
        numbers = cols.columns_with_role(roles, cols.NUMBER)
        if col not in suitable:
            raise ToolError(
                f"Для аргумента col нужна колонка с повторяющимися "
                f"значениями, «{col}» не подходит. Подходят: "
                f"{', '.join(suitable) or 'нет'}.")
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
        positions = range(len(shown))
        axes.bar(positions, shown / scale,
                 color=[GROUP_COLORS[groups[v]] for v in shown.index])
        axes.set_xticks(positions,
                        [str(v)[:LABEL_CHARS] for v in shown.index])
        axes.set_ylabel(column_label(value_col, scale_word),
                        color=style.TEXT)
        axes.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _: format_number(value)))
        axes.tick_params(axis="x", rotation=30)
        line = axes.twinx()
        line.plot(positions, 100 * share.cumsum().head(MAX_BARS),
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
        if len(totals) > MAX_BARS:
            facts.append(f"На графике {MAX_BARS} самых крупных значений, "
                         "группы посчитаны по всем.")
        key = f"abc_analysis:{col}:{value_col}"
        return publish_chart(self, dataset, key, title, figure, facts,
                             excluded)
