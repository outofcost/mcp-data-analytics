"""Отчёт: правила для выводов модели, содержание и текст отчёта.

Форму отчёта задаёт сервер. Модель присылает выводы и рекомендации
объектами (короткая фраза и пояснение с цифрой), сервер проверяет их по
правилам из этого файла и раскладывает по разделам в одном порядке. Поэтому
отчёт выглядит одинаково у любой модели.

Содержание отчёта лежит в ``Report``. По нему пишется Markdown (здесь)
и рисуется PDF (``report_pdf.py``): разойтись они не могут.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from analytics_mcp.store import Chart
from analytics_mcp.style import (column_label, column_title, format_number,
                                 plural, split_unit)

# Границы из описаний Conclusion и Recommendation в models.py.
CONCLUSIONS = (3, 5)        # сколько выводов в отчёте
RECOMMENDATIONS = (2, 4)    # сколько рекомендаций
HEADLINE_WORDS = 8
ACTION_WORDS = 10
BODY_CHARS = 180

MAX_TILES = 4
NBSP = "\u00a0"             # неразрывный пробел: число не рвётся на строки
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Сокращения, у которых точка в конце фразы остаётся.
ABBREVIATIONS = ("руб.", "шт.", "тыс.", "млн.", "г.", "гг.")
# Строки ответа графика, которые нужны модели, а читателю отчёта нет.
SERVICE_FACTS = ("Значений в колонке", "Строк в расчёте", "Строк:", "Период:")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])")
# Строка об очистке в ответе для чата: счётчик из clean_data, фраза
# и формы слова после числа.
CLEANING_PHRASES = (
    ("duplicates", "удалил {} {}", ("дубликат", "дубликата", "дубликатов")),
    ("dropped", "удалил {} {} с пропусками", ("строку", "строки", "строк")),
    ("filled", "заполнил {} {}", ("пропуск", "пропуска", "пропусков")),
    ("spelling", "привёл к одному написанию {} {}",
     ("значение", "значения", "значений")),
    ("outliers", "исключил из расчёта {} {} с выбросами",
     ("строку", "строки", "строк")),
    ("removed_outliers", "удалил {} {} с выбросами",
     ("строку", "строки", "строк")),
)
CHAT_ACTIONS = 3            # столько рекомендаций идёт в ответ для чата
HOW_BUILT = ("Как собран отчёт. Цифры и графики посчитал сервер. Выводы "
             "и рекомендации сформулировала языковая модель по этим цифрам. "
             "Строк, помеченных как выбросы и не вошедших в расчёт: {}.")


@dataclass
class Report:
    """Содержание отчёта в порядке разделов."""

    title: str
    source: str                             # имя файла с данными
    period: str                             # «01.01.2023 – 25.12.2024»
    rows: int                               # строк в расчёте
    created: str                            # дата отчёта
    tiles: list[tuple[str, str]]            # главные числа: подпись, число
    conclusions: list[tuple[str, str]]      # утверждение и пояснение
    recommendations: list[tuple[str, str]]  # действие и основание
    charts: list[Chart]
    reading: list[str]                      # что сделано при чтении файла
    cleaning: list[str]                     # что сделала очистка
    excluded: int                           # строк с выбросами вне расчёта

    @property
    def about(self) -> list[str]:
        """Строка о данных по частям: файл, период, число строк."""
        rows = (f"{format_number(self.rows)} "
                f"{plural(self.rows, 'строка', 'строки', 'строк')} в расчёте")
        return [part for part in (self.source, self.period, rows) if part]

    @property
    def how_built(self) -> str:
        """Абзац о том, кто считал цифры и кто писал выводы."""
        return HOW_BUILT.format(self.excluded)


def word_count(text: str) -> int:
    """Считает слова. Число с разрядами идёт за одно, скобки не в счёт."""
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"(?<=\d)\s(?=\d{3}(?!\d))", "", text)
    return len(text.split())


def check_points(name: str, points: list[tuple[str, str]],
                 fields: tuple[str, str], limits: tuple[int, int],
                 max_words: int, need_digit: bool) -> list[str]:
    """Проверяет список выводов или рекомендаций, возвращает нарушения.

    Args:
        name: имя аргумента save_report, оно идёт в текст нарушения.
        points: пункты парами: короткая фраза и пояснение.
        fields: имена этих двух полей в схеме.
        limits: наименьшее и наибольшее число пунктов.
        max_words: сколько слов допустимо в короткой фразе.
        need_digit: требовать ли цифру в пояснении.
    """
    low, high = limits
    head_field, body_field = fields
    problems = []
    if not low <= len(points) <= high:
        advice = ("Оставьте самые важные." if len(points) > high
                  else "Добавьте недостающие.")
        problems.append(f"{name}: пунктов {len(points)}, нужно от {low} до "
                        f"{high}. {advice}")
    for number, (head, body) in enumerate(points, start=1):
        where = f"{name}, пункт {number}"
        words = word_count(head)
        if not words:
            problems.append(f"{where}, {head_field}: пусто. Напишите "
                            f"фразу до {max_words} слов.")
        if words > max_words:
            problems.append(
                f"{where}, {head_field}: слов {words}, нужно не больше "
                f"{max_words}. Подробности перенесите в {body_field}.")
        if len(body) > BODY_CHARS:
            problems.append(
                f"{where}, {body_field}: знаков {len(body)}, нужно не "
                f"больше {BODY_CHARS}. Оставьте одно-два предложения.")
        if need_digit and not re.search(r"\d", body):
            problems.append(
                f"{where}, {body_field}: нет ни одной цифры. Добавьте "
                "число из collect_findings.")
        elif not body:
            problems.append(f"{where}, {body_field}: пусто. Напишите "
                            "основание одним предложением.")
    return problems


def tidy(text: str, columns: Iterable[str] = ()) -> str:
    """Приводит строку отчёта к одному виду.

    Имя колонки из файла заменяет её подписью («Sales» на «Продажи»): так
    текст совпадает с заголовками графиков. Даты пишет как 25.12.2024,
    вместо дефиса перед числом ставит знак минуса, вместо тире перед
    числом двоеточие, разряды числа склеивает неразрывным пробелом.
    """
    for name in columns:
        if column_title(name) != name:
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)",
                          column_title(name), text)
    text = ISO_DATE.sub(r"\3.\2.\1", text)
    text = re.sub(r" — (?=\d)", ": ", text)
    text = re.sub(r"(?<![\w,.])-(?=\d)", "−", text)
    return re.sub(r"(?<=\d) (?=\d{3}(?!\d))", NBSP, text)


def phrase(text: str) -> str:
    """Убирает точку в конце короткой фразы, кроме точки сокращения."""
    text = text.strip()
    return text if text.endswith(ABBREVIATIONS) else text.rstrip(".")


def sentence(text: str) -> str:
    """Пишет строку журнала предложением: с заглавной буквы и с точкой."""
    return text[:1].upper() + text[1:].rstrip(".") + "."


def caption(chart: Chart) -> str:
    """Собирает подпись под графиком из его фактов, без служебных строк."""
    return " ".join(fact for fact in chart.facts
                    if not fact.startswith(SERVICE_FACTS))


def key_numbers(facts: dict[str, Any] | None,
                profit: str | None) -> list[tuple[str, str]]:
    """Собирает до четырёх главных чисел отчёта: подпись и значение.

    Порядок: главный показатель, прибыль, маржа, остальные суммы, среднее
    за месяц. Последним идёт длина периода, если в данных есть даты.
    Без collect_findings цифр нет, и блок в отчёт не попадает.
    """
    if not facts:
        return []
    totals, measure = facts["итоги"], facts["главный_показатель"]
    names = [name for name in dict.fromkeys([measure, profit, *totals])
             if name in totals]
    tiles = [(column_label(name), format_number(totals[name]))
             for name in names]
    if "маржа_процент" in facts:
        tiles.insert(2, ("Маржа", f"{format_number(facts['маржа_процент'])}%"))
    months = facts.get("динамика_по_месяцам")
    if months:
        unit = split_unit(measure)[1]
        tiles.append(("Среднее за месяц" + (f", {unit}" if unit else ""),
                      format_number(months["среднее_за_месяц"])))
        count = months["месяцев"]
        word = plural(count, "месяц", "месяца", "месяцев")
        tiles = tiles[:MAX_TILES - 1] + [("Период", f"{count} {word}")]
    return tiles[:MAX_TILES]


def to_markdown(report: Report) -> list[str]:
    """Пишет отчёт строками Markdown в том же порядке, что в PDF."""
    lines = [f"# {report.title}", "",
             " · ".join([*report.about, f"отчёт от {report.created}"]), ""]
    if report.tiles:
        lines += ["## Главное", ""]
        lines += [f"- {label}: {value}" for label, value in report.tiles]
        lines.append("")
    for heading, points in (("Выводы", report.conclusions),
                            ("Рекомендации", report.recommendations)):
        lines += [f"## {heading}", ""]
        lines += [f"{number}. **{head.rstrip('.')}.** {body}"
                  for number, (head, body) in enumerate(points, start=1)]
        lines.append("")
    if report.charts:
        lines += ["## Графики", ""]
    for chart in report.charts:
        lines += [f"### {chart.title}", "",
                  f"![{chart.title}]({chart.path.name})", "",
                  caption(chart), ""]
    lines += ["## Что сделано с данными", ""]
    for heading, notes in (("При чтении файла", report.reading),
                           ("При очистке", report.cleaning)):
        if notes:
            lines += [f"### {heading}", ""]
            lines += [f"- {note}" for note in notes]
            lines.append("")
    lines += [report.how_built, ""]
    return lines


def cleaning_summary(counts: dict[str, int] | None) -> str:
    """Пишет одной строкой, что сделала очистка, по её счётчикам."""
    if counts is None:
        return "Очистка не выполнялась."
    parts = [template.format(counts[key], plural(counts[key], *forms))
             for key, template, forms in CLEANING_PHRASES if counts.get(key)]
    if not parts:
        return "Очистка: данные не менялись."
    return "Очистка: " + ", ".join(parts) + "."


def chat_summary(report: Report, counts: dict[str, int] | None,
                 link: str, pages: int) -> str:
    """Собирает короткий ответ для чата из содержания отчёта.

    Текст пишет сервер, поэтому он одинаков у любой модели: строка
    о данных, все выводы (утверждение и первое предложение пояснения),
    первые три рекомендации, строка об очистке и где лежит отчёт. Имён
    файлов графиков в нём нет. Разметка одна: жирный текст в звёздочках.

    Args:
        report: содержание отчёта.
        counts: счётчики очистки из clean_data или None без очистки.
        link: ссылка на PDF или путь к нему.
        pages: сколько страниц в PDF.
    """
    lines = [f"**{report.title}**",
             "Данные: " + ", ".join(report.about) + ".", "", "**Выводы**"]
    lines += [f"{number}. {head.rstrip('.')}. {SENTENCE_END.split(body)[0]}"
              for number, (head, body) in enumerate(report.conclusions, 1)]
    lines += ["", "**Что сделать**"]
    lines += [f"{number}. {head.rstrip('.')}." for number, (head, _)
              in enumerate(report.recommendations[:CHAT_ACTIONS], 1)]
    charts = len(report.charts)
    lines += [
        "", cleaning_summary(counts),
        f"Полный отчёт: {link}, {pages} "
        f"{plural(pages, 'страница', 'страницы', 'страниц')}, {charts} "
        f"{plural(charts, 'график', 'графика', 'графиков')}."]
    return "\n".join(lines).replace(NBSP, " ")
