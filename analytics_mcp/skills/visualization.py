"""Скилл визуализации: графики и подбор графика по типам колонок.

Каждый инструмент с графиком возвращает два блока: текст с тем, что видно
на графике (с числами), и саму картинку в формате PNG. Картинка также
сохраняется на диск: из этих файлов собирается отчёт.
"""

import math
from typing import Annotated, Literal

import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from analytics_mcp import columns as cols
from analytics_mcp import style
from analytics_mcp.charts import publish_chart
from analytics_mcp.models import ChartSuggestion, SuggestResult
from analytics_mcp.registry import Skill, register_skill, tool
from analytics_mcp.store import Analysis, Dataset
from analytics_mcp.style import (column_label, column_title,
                                 format_number)

MIN_CHARTS = 3
MAX_BARS = 12
MAX_LINES = 5
MAX_TICKS = 12
ROLE_NAMES = {cols.DATE: "дата", cols.NUMBER: "число",
              cols.CATEGORY: "категория"}
# Шаг по времени: код периода pandas, слово для подписи и для заголовка.
PERIODS = {"day": ("D", "День", "по дням"),
           "week": ("W", "Неделя", "по неделям"),
           "month": ("M", "Месяц", "по месяцам")}
DATASET_ID = "Идентификатор таблицы. После очистки: из ответа clean_data"


def period_label(period: pd.Period, step: str) -> str:
    """Подписывает точку на оси времени по-русски."""
    start = period.start_time
    if step == "month":
        return f"{style.MONTHS[start.month - 1]}\n{start.year}"
    return start.strftime("%d.%m\n%Y")


def percent(part: float, whole: float, signed: bool = False) -> str:
    """Пишет долю или изменение (со знаком) в процентах, с запятой."""
    if not whole:
        return "н/д"
    text = f"{100 * part / whole:+.1f}%" if signed else (
        f"{100 * part / whole:.1f}%")
    return text.replace(".", ",")


@register_skill
class VisualizationSkill(Skill):
    """Этап 3. Строит графики по заданным параметрам."""

    stage = 30
    title = "Графики"
    guide = (f"Строит графики. Нужно не меньше {MIN_CHARTS} разных. "
             "suggest_charts подбирает подходящие по типам колонок и "
             "возвращает готовые вызовы.")

    def is_done(self, analysis: Analysis) -> bool:
        """Этап выполнен, когда построено нужное число графиков."""
        target = analysis.extra.get("chart_target", MIN_CHARTS)
        return len(analysis.charts) >= target

    def hint(self, analysis: Analysis) -> str:
        """Подсказывает подобрать графики или построить следующий."""
        if "chart_target" not in analysis.extra:
            return (f"Вызовите suggest_charts(dataset_id=\""
                    f"{analysis.current_id}\"): он подберёт графики по "
                    "типам колонок.")
        target = analysis.extra["chart_target"]
        return (f"Построено графиков: {len(analysis.charts)} из {target}. "
                "Постройте следующий непостроенный график из списка "
                "suggest_charts.")

    def _column(self, dataset: Dataset, name: str, role: str,
                argument: str) -> str:
        """Проверяет, что колонка есть и подходит инструменту по типу."""
        roles = dataset.roles
        suitable = ", ".join(cols.columns_with_role(roles, role)) or "нет"
        if name not in roles:
            raise ToolError(
                f"Колонки «{name}» в таблице нет. Для аргумента {argument} "
                f"нужна колонка типа «{ROLE_NAMES[role]}». Подходят: "
                f"{suitable}.")
        if roles[name] != role:
            raise ToolError(
                f"Колонка «{name}» имеет тип «{roles[name]}», а для "
                f"аргумента {argument} нужна колонка типа "
                f"«{ROLE_NAMES[role]}». Подходят: {suitable}.")
        return name

    @tool
    def suggest_charts(
        self,
        dataset_id: Annotated[str, Field(description=DATASET_ID)],
    ) -> SuggestResult:
        """Подбирает графики по типам колонок и возвращает готовые вызовы.

        Правила: дата и число дают график динамики; категория и число дают
        сравнение по категориям; число даёт гистограмму; две числовые
        колонки и больше дают матрицу корреляций. Главный показатель
        выбирается по имени колонки (выручка, продажи, сумма), иначе это
        первая числовая колонка.
        """
        dataset = self.store.get(dataset_id)
        roles = dataset.roles
        dates = cols.columns_with_role(roles, cols.DATE)
        numbers = cols.columns_with_role(roles, cols.NUMBER)
        categories = cols.columns_with_role(roles, cols.CATEGORY)
        measure, profit = cols.pick_measure(roles), cols.pick_profit(roles)

        found: list[tuple[str, dict[str, str], str]] = []
        if dates and measure:
            found.append(("plot_trend", {"x_col": dates[0], "y_col": measure},
                          "есть дата и число: динамика показателя во "
                          "времени"))
        for name in categories[:2]:
            arguments = {"col": name}
            if measure:
                arguments["value_col"] = measure
            found.append(("plot_distribution", arguments,
                          "есть категория и число: сравнение по значениям "
                          f"колонки «{name}»"))
        if len(numbers) >= 2:
            found.append(("correlation_analysis", {},
                          "числовых колонок две или больше: связи между "
                          "показателями"))
        if measure:
            found.append(("plot_distribution", {"col": measure},
                          "есть число: как распределены его значения"))
        if profit and profit != measure and categories:
            found.append(("plot_distribution",
                          {"col": categories[0], "value_col": profit},
                          "есть колонка с прибылью: где она отрицательная"))

        built = {chart.key for chart in dataset.analysis.charts}
        suggestions = []
        for name, arguments, why in found:
            key = ":".join([name, *arguments.values()])
            suggestions.append(ChartSuggestion(
                tool=name,
                arguments={"dataset_id": dataset_id, **arguments},
                why=why,
                built=any(k.startswith(key) for k in built),
            ))
        dataset.analysis.extra["chart_target"] = min(MIN_CHARTS,
                                                     len(suggestions))
        return SuggestResult(dataset_id=dataset_id, suggestions=suggestions,
                             next_step=self.next_step(dataset))

    @tool
    def plot_trend(
        self,
        dataset_id: Annotated[str, Field(description=DATASET_ID)],
        x_col: Annotated[str, Field(description="Колонка с датой")],
        y_col: Annotated[str, Field(
            description="Числовая колонка, значения суммируются "
                        "по периодам")],
        freq: Annotated[Literal["auto", "day", "week", "month"], Field(
            description="Шаг по времени. auto выбирает по длине периода: "
                        "больше 120 дней: месяц, больше 21 дня: неделя, "
                        "иначе день")] = "auto",
        group_col: Annotated[str, Field(
            description="Категория для разбивки на отдельные линии, до "
                        "пяти самых крупных значений. Пусто: одна линия")
        ] = "",
    ) -> list[str | Image]:
        """Строит график тренда: сумма показателя по периодам времени.

        Возвращает текст (период, сумма, максимум, минимум, изменение
        последнего периода к первому) и картинку PNG.
        """
        dataset = self.store.get(dataset_id)
        self._column(dataset, x_col, cols.DATE, "x_col")
        self._column(dataset, y_col, cols.NUMBER, "y_col")
        if group_col:
            self._column(dataset, group_col, cols.CATEGORY, "group_col")
        frame, excluded = dataset.working_frame()
        data = frame.dropna(subset=[x_col, y_col])
        if data.empty:
            raise ToolError(f"В колонках «{x_col}» и «{y_col}» нет строк, "
                            "где заполнены оба значения.")

        if freq == "auto":
            days = (data[x_col].max() - data[x_col].min()).days
            freq = "month" if days > 120 else "week" if days > 21 else "day"
        code, axis_word, title_word = PERIODS[freq]
        periods = data[x_col].dt.to_period(code)
        full_range = pd.period_range(periods.min(), periods.max(), freq=code)
        total = data.groupby(periods)[y_col].sum().reindex(full_range,
                                                           fill_value=0)

        scale, scale_word = style.pick_scale(total.max())
        title = f"{column_title(y_col)} {title_word}"
        figure, axes = style.new_figure(title)
        positions = range(len(total))
        if group_col:
            top = data.groupby(group_col)[y_col].sum().nlargest(MAX_LINES)
            for color, value in zip(style.SERIES_COLORS, top.index):
                part = data[data[group_col] == value]
                line = part.groupby(part[x_col].dt.to_period(code))[y_col]
                line = line.sum().reindex(full_range, fill_value=0)
                axes.plot(positions, line / scale, color=color, linewidth=2,
                          label=str(value))
            axes.legend(frameon=False, fontsize=9, title_fontsize=9,
                        title=column_title(group_col))
            title += f" по колонке «{column_title(group_col)}»"
            axes.set_title(title, loc="left", fontsize=13, color=style.TEXT,
                           pad=12)
        else:
            axes.plot(positions, total / scale, color=style.GREEN,
                      linewidth=2.5, marker="o", markersize=4,
                      markerfacecolor=style.DARK_GREEN,
                      markeredgecolor=style.DARK_GREEN)
            peak = int(total.to_numpy().argmax())
            axes.annotate(format_number(total.iloc[peak] / scale),
                          (peak, total.iloc[peak] / scale),
                          textcoords="offset points", xytext=(0, 8),
                          ha="center", fontsize=9, color=style.DARK_GREEN)
        step = math.ceil(len(total) / MAX_TICKS)
        axes.set_xticks(list(positions)[::step])
        axes.set_xticklabels([period_label(p, freq)
                              for p in total.index[::step]])
        axes.set_xlabel(axis_word, color=style.TEXT)
        axes.set_ylabel(column_label(y_col, scale_word), color=style.TEXT)
        axes.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _: format_number(value)))

        def name_of(period: pd.Period) -> str:
            return period_label(period, freq).replace("\n", " ")

        first, last = total.iloc[0], total.iloc[-1]
        facts = [
            f"Период: с {name_of(total.index[0])} по "
            f"{name_of(total.index[-1])}, точек: {len(total)}.",
            f"Сумма за период: {format_number(total.sum())}.",
            f"Максимум: {name_of(total.idxmax())}, "
            f"{format_number(total.max())}.",
            f"Минимум: {name_of(total.idxmin())}, "
            f"{format_number(total.min())}.",
            f"Изменение последнего периода к первому: "
            f"{percent(last - first, first, signed=True)}.",
        ]
        key = f"plot_trend:{x_col}:{y_col}:{freq}:{group_col}"
        return publish_chart(self, dataset, key, title, figure, facts,
                             excluded)

    @tool
    def plot_distribution(
        self,
        dataset_id: Annotated[str, Field(description=DATASET_ID)],
        col: Annotated[str, Field(
            description="Колонка. Числовая даёт гистограмму, категория "
                        "даёт столбцы по её значениям")],
        value_col: Annotated[str, Field(
            description="Только для категории: числовая колонка, сумма "
                        "которой сравнивается. Пусто: главный показатель "
                        "таблицы, а если чисел нет, число строк")] = "",
    ) -> list[str | Image]:
        """Строит распределение: гистограмму числа или столбцы по категории.

        Возвращает текст (для числа: медиана, среднее, границы; для
        категории: крупнейшие значения с долями, отрицательные суммы)
        и картинку PNG.
        """
        dataset = self.store.get(dataset_id)
        roles = dataset.roles
        frame, excluded = dataset.working_frame()
        if roles.get(col) == cols.NUMBER:
            title, figure, facts = self._histogram(frame, col)
            key = f"plot_distribution:{col}"
        elif roles.get(col) == cols.CATEGORY:
            value_col = value_col or cols.pick_measure(roles) or ""
            if value_col:
                self._column(dataset, value_col, cols.NUMBER, "value_col")
            title, figure, facts = self._bars(frame, col, value_col)
            key = f"plot_distribution:{col}:{value_col}"
        else:
            suitable = ", ".join(
                cols.columns_with_role(roles, cols.NUMBER)
                + cols.columns_with_role(roles, cols.CATEGORY))
            actual = (f"имеет тип «{roles[col]}»" if col in roles
                      else "в таблице отсутствует")
            raise ToolError(
                f"Колонка «{col}» {actual}. Для распределения нужна "
                f"числовая колонка или категория. Подходят: {suitable}. "
                "Для колонки с датой вызовите plot_trend.")
        return publish_chart(self, dataset, key, title, figure, facts,
                             excluded)

    @staticmethod
    def _histogram(frame: pd.DataFrame,
                   name: str) -> tuple[str, Figure, list[str]]:
        """Рисует гистограмму числовой колонки с линией медианы."""
        values = frame[name].dropna()
        if values.empty:
            raise ToolError(f"В колонке «{name}» нет значений.")
        scale, scale_word = style.pick_scale(values.abs().max())
        title = f"Распределение значений: {column_title(name)}"
        figure, axes = style.new_figure(title)
        bins = min(20, max(5, round(math.sqrt(len(values)))))
        axes.hist(values / scale, bins=bins, color=style.GREEN,
                  edgecolor="white")
        median = values.median()
        axes.axvline(median / scale, color=style.DARK_GREEN, linestyle="--",
                     linewidth=1.5,
                     label=f"Медиана: {format_number(median / scale)}")
        axes.legend(frameon=False, fontsize=9)
        axes.set_xlabel(column_label(name, scale_word), color=style.TEXT)
        axes.set_ylabel("Число строк", color=style.TEXT)
        axes.xaxis.set_major_formatter(
            FuncFormatter(lambda value, _: format_number(value)))
        facts = [
            f"Строк: {len(values)}.",
            f"Медиана: {format_number(median)}, среднее: "
            f"{format_number(values.mean())}.",
            f"Минимум: {format_number(values.min())}, максимум: "
            f"{format_number(values.max())}.",
        ]
        return title, figure, facts

    @staticmethod
    def _bars(frame: pd.DataFrame, name: str,
              value_col: str) -> tuple[str, Figure, list[str]]:
        """Рисует столбцы по значениям категории, от большего к меньшему."""
        if value_col:
            totals = frame.groupby(name)[value_col].sum()
            measure = column_title(value_col)
        else:
            totals = frame[name].value_counts()
            measure = "Число строк"
        totals = totals.sort_values(ascending=False)
        if totals.empty:
            raise ToolError(f"В колонке «{name}» нет значений.")
        shown = totals
        if len(totals) > MAX_BARS:
            shown = totals.head(MAX_BARS - 1)
            shown["Прочие"] = totals.iloc[MAX_BARS - 1:].sum()

        scale, scale_word = style.pick_scale(shown.abs().max())
        title = f"{measure} по колонке «{column_title(name)}»"
        figure, axes = style.new_figure(title)
        colors = [style.GREY if value < 0 else style.GREEN
                  for value in shown[::-1]]
        bars = axes.barh([str(v) for v in shown.index[::-1]],
                         shown[::-1] / scale, color=colors)
        axes.bar_label(bars, labels=[format_number(v / scale)
                                     for v in shown[::-1]],
                       padding=3, fontsize=9, color=style.TEXT)
        axes.grid(False, axis="y")
        axes.grid(axis="x", color=style.LIGHT_GREY, linewidth=0.8)
        axes.margins(x=0.12)
        axes.set_xlabel(column_label(value_col, scale_word) if value_col
                        else measure, color=style.TEXT)
        axes.xaxis.set_major_formatter(
            FuncFormatter(lambda value, _: format_number(value)))

        whole = totals.sum()
        facts = [f"Значений в колонке «{name}»: {len(totals)}."]
        for value, amount in totals.head(3).items():
            facts.append(f"{value}: {format_number(amount)} "
                         f"({percent(amount, whole)} от суммы).")
        if len(totals) > 3:
            facts.append(f"Меньше всех: {totals.index[-1]}, "
                         f"{format_number(totals.iloc[-1])}.")
        negative = totals[totals < 0]
        if len(negative):
            facts.append("Отрицательная сумма: " + ", ".join(
                f"{value} ({format_number(amount)})"
                for value, amount in negative.items()) + ".")
        return title, figure, facts

    @tool
    def correlation_analysis(
        self,
        dataset_id: Annotated[str, Field(description=DATASET_ID)],
    ) -> list[str | Image]:
        """Строит матрицу корреляций числовых колонок (тепловая карта).

        Возвращает текст (пары колонок от самой сильной связи к слабой,
        коэффициент Пирсона) и картинку PNG. Нужны минимум две числовые
        колонки.
        """
        dataset = self.store.get(dataset_id)
        numbers = cols.columns_with_role(dataset.roles, cols.NUMBER)
        if len(numbers) < 2:
            raise ToolError(
                "Для корреляций нужны минимум две числовые колонки. В "
                f"таблице их {len(numbers)}: {', '.join(numbers) or 'нет'}. "
                "Постройте другой график из suggest_charts.")
        frame, excluded = dataset.working_frame()
        matrix = frame[numbers].corr()
        labels = [column_title(name) for name in numbers]

        title = "Корреляции между числовыми показателями"
        figure, axes = style.new_figure(title)
        image = axes.imshow(matrix, cmap=style.CORRELATION_MAP, vmin=-1,
                            vmax=1)
        axes.grid(False)
        axes.spines[["left", "bottom"]].set_visible(False)
        axes.set_xticks(range(len(labels)), labels)
        axes.set_yticks(range(len(labels)), labels)
        for row in range(len(numbers)):
            for column in range(len(numbers)):
                value = matrix.iloc[row, column]
                axes.text(column, row, f"{value:.2f}".replace(".", ","),
                          ha="center", va="center", fontsize=10,
                          color="white" if abs(value) > 0.6 else style.TEXT)
        bar = figure.colorbar(image, ax=axes, fraction=0.046, pad=0.04)
        bar.set_label("Коэффициент корреляции Пирсона", color=style.TEXT)

        pairs = [(numbers[a], numbers[b], matrix.iloc[a, b])
                 for a in range(len(numbers))
                 for b in range(a + 1, len(numbers))]
        pairs.sort(key=lambda pair: abs(pair[2]), reverse=True)
        facts = [f"Строк в расчёте: {len(frame)}."]
        for first, second, value in pairs[:6]:
            strength = ("сильная" if abs(value) >= 0.7 else
                        "заметная" if abs(value) >= 0.4 else "слабая")
            direction = "прямая" if value >= 0 else "обратная"
            facts.append(f"{first} и {second}: "
                         f"{value:+.2f}".replace(".", ",")
                         + f" ({strength} {direction} связь).")
        facts.append("Корреляция показывает, что величины меняются вместе. "
                     "Причину она не доказывает.")
        return publish_chart(self, dataset, "correlation_analysis", title,
                             figure, facts, excluded)
