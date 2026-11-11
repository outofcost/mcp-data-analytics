"""Скилл выводов: цифры для выводов и сборка отчёта.

Разделение труда такое: цифры считает код, текст пишет модель. Инструмент
``collect_findings`` отдаёт модели готовые цифры, модель формулирует по
ним выводы и рекомендации, ``save_report`` собирает из этого отчёт
с графиками и журналом очистки.
"""

import secrets
import webbrowser
from datetime import date
from typing import Annotated, Any

import pandas as pd
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from analytics_mcp import columns as col
from analytics_mcp import report as rep
from analytics_mcp.models import (Conclusion, FindingsResult,
                                  Recommendation, ReportResult)
from analytics_mcp.registry import Skill, register_skill, tool
from analytics_mcp.report_pdf import write_pdf
from analytics_mcp.store import Analysis, Chart
from analytics_mcp.style import MONTHS_FULL, format_number

MAX_CATEGORY_COLUMNS = 4
MAX_VALUES = 12
MONTHS_FOR_SEASONALITY = 24
# Слова в имени колонки, по которым узнаётся процент или доля.
PERCENT_WORDS = ("%", "процент", "скидк", "discount", "доля", "share")
HOW_TO_USE = (
    "Сформулируйте от 3 до 5 выводов и от 2 до 4 практических "
    "рекомендаций, самые важные первыми. Вывод это короткое утверждение "
    "(headline, до 8 слов) и пояснение с цифрой из facts (evidence, до 180 "
    "знаков). Рекомендация это действие (action, до 10 слов) и основание "
    "(reason, до 180 знаков). Свои цифры не считайте. Учтите сведения об "
    "очистке и исключённых выбросах. Затем вызовите save_report.")


def rounded(value: float) -> float:
    """Округляет число для ответа: большие до целых, малые до сотых."""
    value = float(value)
    return round(value) if abs(value) >= 100 else round(value, 2)


def change_percent(new: float, old: float) -> float | None:
    """Считает изменение в процентах или возвращает None при нулевой базе."""
    return round(100 * (new - old) / old, 1) if old else None


def month_name(period: pd.Period) -> str:
    """Пишет месяц словами: «декабрь 2024»."""
    return f"{MONTHS_FULL[period.month - 1]} {period.year}"


def time_facts(data: pd.DataFrame, date_col: str,
               measure: str) -> dict[str, Any]:
    """Считает динамику по месяцам, сезонность и суммы по годам."""
    facts: dict[str, Any] = {"период": {
        "начало": data[date_col].min().date().isoformat(),
        "конец": data[date_col].max().date().isoformat(),
    }}
    months = data[date_col].dt.to_period("M")
    monthly = data.groupby(months)[measure].sum().reindex(
        pd.period_range(months.min(), months.max(), freq="M"), fill_value=0)
    if len(monthly) >= 2:
        facts["динамика_по_месяцам"] = {
            "показатель": measure,
            "месяцев": len(monthly),
            "среднее_за_месяц": rounded(monthly.mean()),
            "лучший_месяц": {"месяц": month_name(monthly.idxmax()),
                             "значение": rounded(monthly.max())},
            "худший_месяц": {"месяц": month_name(monthly.idxmin()),
                             "значение": rounded(monthly.min())},
        }
    # Сезонность видна только на двух полных годах: по одному году её
    # не отличить от разового события.
    if len(monthly) >= MONTHS_FOR_SEASONALITY:
        by_month = monthly.groupby(monthly.index.month).mean()
        index = (by_month / by_month.mean()).sort_values(ascending=False)
        facts["сезонность"] = {
            "как_считается": "среднее значение месяца, делённое на среднее "
                             "по всем месяцам; 1,0 это обычный месяц",
            "самые_сильные_месяцы": {MONTHS_FULL[m - 1]: round(v, 2)
                                     for m, v in index.head(2).items()},
            "самые_слабые_месяцы": {MONTHS_FULL[m - 1]: round(v, 2)
                                    for m, v in index.tail(2).items()},
        }
    yearly = data.groupby(data[date_col].dt.year)[measure].sum()
    if len(yearly) >= 2:
        facts["по_годам"] = {
            "суммы": {str(year): rounded(v) for year, v in yearly.items()},
            "последний_год_к_предыдущему_процент": change_percent(
                yearly.iloc[-1], yearly.iloc[-2]),
            "месяцев_с_данными": {
                str(year): int(count) for year, count
                in months.groupby(data[date_col].dt.year).nunique().items()},
        }
    return facts


def category_facts(data: pd.DataFrame, name: str, measure: str,
                   profit: str | None,
                   date_col: str | None) -> dict[str, Any]:
    """Считает разрез по одной категории: доли, маржу, рост."""
    totals = data.groupby(name)[measure].sum().sort_values(ascending=False)
    whole = totals.sum()
    facts: dict[str, Any] = {
        "показатель": measure,
        "значений": len(totals),
        "суммы_и_доли": {
            str(value): {"сумма": rounded(amount),
                         "доля_процент": (round(100 * amount / whole, 1)
                                          if whole else None)}
            for value, amount in totals.head(MAX_VALUES).items()},
    }
    if profit:
        gains = data.groupby(name)[profit].sum()
        margin = (100 * gains / totals).round(1)
        facts["маржа_процент"] = {str(value): margin[value]
                                  for value in totals.head(MAX_VALUES).index}
        negative = gains[gains < 0]
        if len(negative):
            facts["отрицательная_прибыль"] = {
                str(value): rounded(amount)
                for value, amount in negative.items()}
    if date_col:
        middle = (data[date_col].min()
                  + (data[date_col].max() - data[date_col].min()) / 2)
        first = data[data[date_col] <= middle].groupby(name)[measure].sum()
        second = data[data[date_col] > middle].groupby(name)[measure].sum()
        facts["вторая_половина_периода_к_первой_процент"] = {
            str(value): change_percent(second.get(value, 0),
                                       first.get(value, 0))
            for value in totals.head(MAX_VALUES).index}
        facts["граница_половин"] = middle.date().isoformat()
    return facts


def is_number(value: Any) -> bool:
    """Отвечает, число ли это (логическое значение числом не считается)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def render(value: Any, depth: int = 0) -> list[str]:
    """Превращает вложенные цифры в список Markdown для отчёта."""
    pad = "  " * depth
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).replace("_", " ")
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}- {name}:")
                lines += render(item, depth + 1)
            else:
                shown = ("нет данных" if item is None
                         else format_number(item) if is_number(item)
                         else item)
                lines.append(f"{pad}- {name}: {shown}")
    elif isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return [f"{pad}- " + "; ".join(str(item) for item in value)]
        for item in value:
            lines += render(item, depth)
    return lines


@register_skill
class InsightGenerationSkill(Skill):
    """Этап 4. Отдаёт цифры для выводов и собирает отчёт."""

    stage = 40
    title = "Выводы"
    guide = ("collect_findings считает цифры для выводов. По ним напишите "
             "выводы и рекомендации и передайте их в save_report: он "
             "соберёт отчёт с графиками и вернёт готовый ответ для "
             "пользователя.")
    rules = (
        "После save_report покажи пользователю текст из поля chat_summary "
        "без изменений: это готовый ответ.",
    )

    def is_done(self, analysis: Analysis) -> bool:
        """Этап выполнен, когда отчёт сохранён."""
        return analysis.report_path is not None

    def hint(self, analysis: Analysis) -> str:
        """Подсказывает собрать цифры или сохранить отчёт."""
        if analysis.findings is None:
            return (f"Вызовите collect_findings(dataset_id=\""
                    f"{analysis.current_id}\").")
        return ("Напишите выводы и рекомендации по цифрам из "
                "collect_findings и вызовите save_report(dataset_id=\""
                f"{analysis.current_id}\", title, conclusions, "
                "recommendations). Вывод: headline и evidence. "
                "Рекомендация: action и reason.")

    @tool(title="Цифры для выводов")
    def collect_findings(
        self,
        dataset_id: Annotated[str, Field(
            description="Идентификатор таблицы. После очистки: из ответа "
                        "clean_data")],
    ) -> FindingsResult:
        """Считает цифры, на которых строятся выводы и рекомендации.

        Итоги по числовым колонкам, динамика по месяцам, сезонность (если
        данных хватает на два года), суммы по годам, разрезы по категориям
        (доли, маржа, рост второй половины периода к первой), самые сильные
        корреляции, сведения об очистке.
        Сам выводов не пишет: их формулирует модель по этим цифрам.
        """
        dataset = self.store.current(dataset_id)
        analysis, roles = dataset.analysis, dataset.roles
        frame, excluded = dataset.working_frame()
        dates = col.columns_with_role(roles, col.DATE)
        numbers = col.columns_with_role(roles, col.NUMBER)
        categories = col.columns_with_role(roles, col.CATEGORY)
        measure, profit = col.pick_measure(roles), col.pick_profit(roles)
        if profit == measure:
            profit = None

        facts: dict[str, Any] = {
            "источник": analysis.source,
            "строк_в_расчёте": len(frame),
            "главный_показатель": measure,
            # Сумма процентов смысла не имеет, в итоги они не идут.
            "итоги": {name: rounded(frame[name].sum()) for name in numbers
                      if not col.has_word(name, PERCENT_WORDS)},
        }
        if measure and profit and frame[measure].sum():
            facts["маржа_процент"] = round(
                100 * frame[profit].sum() / frame[measure].sum(), 1)
        date_col = dates[0] if dates else None
        if date_col and measure:
            facts.update(time_facts(frame.dropna(subset=[date_col, measure]),
                                    date_col, measure))
        if measure:
            facts["по_категориям"] = {
                name: category_facts(frame.dropna(subset=[measure]), name,
                                     measure, profit, date_col)
                for name in categories[:MAX_CATEGORY_COLUMNS]}
        else:
            facts["по_категориям"] = {
                name: {str(value): int(count) for value, count
                       in frame[name].value_counts().head(MAX_VALUES).items()}
                for name in categories[:MAX_CATEGORY_COLUMNS]}
        if len(numbers) >= 2:
            matrix = frame[numbers].corr()
            pairs = [(numbers[a], numbers[b], matrix.iloc[a, b])
                     for a in range(len(numbers))
                     for b in range(a + 1, len(numbers))]
            pairs.sort(key=lambda pair: abs(pair[2]), reverse=True)
            facts["самые_сильные_связи"] = [
                f"{first} и {second}: {value:+.2f}".replace(".", ",")
                for first, second, value in pairs[:3]]
        facts["качество_данных"] = {
            "что_сделала_очистка": (analysis.cleaning_log
                                    or ["очистка не выполнялась"]),
            "строк_с_выбросами_вне_расчёта": excluded,
        }

        analysis.findings = facts
        return FindingsResult(dataset_id=dataset_id, facts=facts,
                              how_to_use=HOW_TO_USE,
                              next_step=self.next_step(dataset))

    @tool(title="Сохранить отчёт")
    def save_report(
        self,
        dataset_id: Annotated[str, Field(
            description="Идентификатор таблицы, по которой шёл анализ")],
        title: Annotated[str, Field(description="Заголовок отчёта")],
        conclusions: Annotated[list[Conclusion], Field(
            description="От 3 до 5 выводов, самый важный первым",
            json_schema_extra={"minItems": 3, "maxItems": 5})],
        recommendations: Annotated[list[Recommendation], Field(
            description="От 2 до 4 рекомендаций, самая важная первой",
            json_schema_extra={"minItems": 2, "maxItems": 4})],
    ) -> ReportResult:
        """Собирает отчёт и сохраняет его в двух видах: Markdown и PDF.

        Выводы и рекомендации передаются объектами: короткая фраза
        и пояснение с цифрой. Если форма нарушена, инструмент возвращает
        список нарушений, вызов нужно исправить и повторить.

        Порядок разделов задаёт сервер: главные числа, выводы,
        рекомендации, все построенные графики с подписями, что сделано
        с данными. В Markdown приложением идут все цифры из
        collect_findings. PDF это один файл с графиками внутри, его удобно
        открыть или переслать. Возвращает готовый короткий ответ для
        пользователя (chat_summary), пути к файлам, ссылку на PDF (если
        сервер работает по HTTP) и список того, чего отчёту не хватает.
        """
        dataset = self.store.current(dataset_id)
        found = [(rep.phrase(item.headline), item.evidence.strip())
                 for item in conclusions]
        advice = [(rep.phrase(item.action), item.reason.strip())
                  for item in recommendations]
        # Число пунктов и длину текста проверяет этот код, а не pydantic:
        # так модель получает все нарушения сразу и по-русски.
        problems = rep.check_points(
            "conclusions", found, ("headline", "evidence"),
            rep.CONCLUSIONS, rep.HEADLINE_WORDS, need_digit=True)
        problems += rep.check_points(
            "recommendations", advice, ("action", "reason"),
            rep.RECOMMENDATIONS, rep.ACTION_WORDS, need_digit=False)
        if problems:
            raise ToolError(
                "save_report не принял аргументы. Исправьте и вызовите "
                "снова:\n" + "\n".join(f"- {text}" for text in problems))
        analysis = dataset.analysis

        # Предупреждения: какие этапы до этого не доведены до конца.
        warnings = [
            f"Этап «{skill.title}» не завершён. {skill.hint(analysis)}"
            for skill in self.workflow.skills
            if skill is not self and not skill.is_done(analysis)]
        if analysis.findings is None:
            warnings.append("collect_findings не вызывался: раздела "
                            "с цифрами в отчёте нет.")

        frame, excluded = dataset.working_frame()
        names = list(dataset.roles)

        def tidy(text: str) -> str:
            """Приводит строку к виду отчёта, имена колонок к подписям."""
            return rep.tidy(text, names)

        facts = analysis.findings or {}
        period = facts.get("период")
        report = rep.Report(
            title=tidy(title.strip()) or "Отчёт по данным",
            source=analysis.source,
            period=(tidy(f"{period['начало']} – {period['конец']}")
                    if period else ""),
            rows=len(frame),
            created=date.today().strftime("%d.%m.%Y"),
            tiles=[(label, tidy(value)) for label, value
                   in rep.key_numbers(analysis.findings,
                                      col.pick_profit(dataset.roles))],
            conclusions=[(tidy(head), tidy(body)) for head, body in found],
            recommendations=[(tidy(head), tidy(body))
                             for head, body in advice],
            charts=[Chart(chart.key, chart.title, chart.path,
                          [tidy(fact) for fact in chart.facts])
                    for chart in analysis.charts],
            reading=[rep.sentence(tidy(note)) for note in dataset.notes],
            cleaning=[rep.sentence(tidy(action))
                      for action in analysis.cleaning_log]
            or ["Очистка не выполнялась."],
            excluded=excluded,
        )
        # Полный список цифр идёт приложением только в Markdown: он нужен
        # для сверки выводов, а в PDF занимал три страницы сплошного списка.
        appendix = []
        if analysis.findings:
            appendix = ["## Приложение. Цифры, на которых стоят выводы", "",
                        *map(tidy, render(analysis.findings)), ""]

        folder = self.settings.output_dir / analysis.root_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "report.md"
        path.write_text("\n".join(rep.to_markdown(report) + appendix),
                        encoding="utf-8")
        # Тот же отчёт одним файлом: в Markdown графики лежат рядом
        # отдельными картинками, в PDF они внутри.
        pdf_path = folder / "report.pdf"
        pages = write_pdf(report, pdf_path)
        analysis.report_path = path

        report_url = ""
        if self.settings.public_url:
            # По HTTP файл лежит на чужой для пользователя машине, поэтому
            # сервер отдаёт его по ссылке со случайным ключом.
            key = secrets.token_urlsafe(16)
            self.settings.report_links[key] = pdf_path
            report_url = f"{self.settings.public_url}/reports/{key}/report.pdf"
        if self.settings.open_report:
            webbrowser.open(pdf_path.resolve().as_uri())
        # Короткий ответ для чата собирает сервер, а не модель: так он
        # одинаков в любом клиенте.
        summary = rep.chat_summary(
            report, analysis.extra.get("cleaning_counts"),
            report_url or self.settings.relative(pdf_path), pages)
        return ReportResult(
            dataset_id=dataset_id,
            chat_summary=summary,
            report_path=self.settings.relative(path),
            pdf_path=self.settings.relative(pdf_path),
            report_url=report_url,
            charts=len(analysis.charts),
            pages=pages,
            warnings=warnings,
            next_step=self.next_step(dataset),
        )
