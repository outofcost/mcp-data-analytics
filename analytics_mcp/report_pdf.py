"""Сборка PDF по содержанию отчёта.

PDF это один файл с графиками внутри: он открывается на телефоне и уходит
в мессенджер. Порядок разделов рассчитан на читателя: ответ на вопрос «что
с данными и что делать» стоит на первой странице, графики идут следом как
доказательство, журнал очистки стоит в конце для того, кто отчёт проверяет.

Содержание приходит готовым в ``Report``: тот же объект пишется в Markdown,
поэтому два вида отчёта совпадают.
"""

import logging
from pathlib import Path

import matplotlib
from fpdf import FPDF

from analytics_mcp.report import Report, caption
from analytics_mcp.style import DARK_GREEN, GREEN, GREY, LIGHT_GREY, TEXT

# Шрифт с кириллицей идёт в комплекте с matplotlib, отдельно его не ставим.
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
FONT = "DejaVu"
TILE_COLOR = "#EDF8F1"
MARGIN = 20             # мм, поля слева и справа
WIDTH = 170             # мм, ширина текста на странице A4
# График вписывается в рамку такого размера. Два графика с подписями
# занимают одну страницу.
IMAGE_WIDTH, IMAGE_HEIGHT = 160, 90
MARK_WIDTH = 7          # мм, место под номер пункта или точку списка
TILE_HEIGHT = 19        # мм, высота плитки с главным числом

# Библиотека шрифтов пишет в журнал каждую вставку шрифта, это шум.
logging.getLogger("fontTools").setLevel(logging.WARNING)


def rgb(color: str) -> tuple[int, int, int]:
    """Переводит цвет вида #2DBE64 в три числа."""
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


class ReportPdf(FPDF):
    """Страница отчёта: шрифт с кириллицей и колонтитул."""

    def __init__(self, origin: str, pages: int) -> None:
        """Подключает шрифт, задаёт поля и запоминает текст колонтитула.

        Args:
            origin: откуда отчёт, левая часть колонтитула.
            pages: сколько в отчёте страниц.
        """
        super().__init__(format="A4")
        self.add_font(FONT, "", FONT_DIR / "DejaVuSans.ttf")
        self.add_font(FONT, "B", FONT_DIR / "DejaVuSans-Bold.ttf")
        self.set_margins(MARGIN, 18, MARGIN)
        self.set_auto_page_break(True, margin=20)
        self.c_margin = 0   # текст начинается ровно от поля, как линии
        self.origin = origin
        self.total_pages = pages

    def footer(self) -> None:
        """Пишет внизу страницы, откуда отчёт, и «страница N из M»."""
        self.set_draw_color(*rgb(LIGHT_GREY))
        self.set_line_width(0.2)
        self.line(MARGIN, self.h - 16, MARGIN + WIDTH, self.h - 16)
        self.set_y(-14)
        self.set_font(FONT, "", 7.5)
        self.set_text_color(*rgb(GREY))
        self.cell(WIDTH / 2, 4, self.origin)
        self.cell(WIDTH / 2, 4, align="R",
                  text=f"страница {self.page_no()} из {self.total_pages}")

    def paragraph(self, text: str, size: float = 9.5, bold: bool = False,
                  color: str = TEXT, indent: float = 0,
                  dry_run: bool = False) -> float:
        """Пишет абзац с переносом строк и возвращает его высоту.

        С dry_run=True ничего не пишет и только считает высоту: так
        проверяется, поместится ли блок на странице.
        """
        self.set_font(FONT, "B" if bold else "", size)
        self.set_text_color(*rgb(color))
        self.set_x(MARGIN + indent)
        return self.multi_cell(0, size * 0.5, text, align="L",
                               new_x="LMARGIN", new_y="NEXT",
                               dry_run=dry_run, output="HEIGHT")

    def keep_together(self, height: float) -> None:
        """Начинает новую страницу, если блок такой высоты не помещается."""
        if self.will_page_break(height):
            self.add_page()

    def section(self, title: str) -> None:
        """Пишет заголовок раздела."""
        self.ln(5)
        self.paragraph(title, size=12.5, bold=True, color=DARK_GREEN)
        self.ln(1.5)

    def mark(self, text: str, size: float) -> None:
        """Ставит слева зелёный номер пункта или точку списка."""
        self.set_font(FONT, "B", size)
        self.set_text_color(*rgb(GREEN))
        self.set_x(MARGIN)
        self.cell(MARK_WIDTH, size * 0.5, text)

    def fit_font(self, text: str, bold: bool, size: float,
                 width: float) -> None:
        """Ставит шрифт и уменьшает кегль, пока строка не войдёт в ширину."""
        self.set_font(FONT, "B" if bold else "", size)
        while self.get_string_width(text) > width and size > 6:
            size -= 0.5
            self.set_font(FONT, "B" if bold else "", size)


def draw_header(pdf: ReportPdf, report: Report) -> None:
    """Рисует шапку: заголовок, зелёную линию и одну строку о данных."""
    pdf.set_title(report.title)
    pdf.paragraph(report.title, size=18, bold=True, color=DARK_GREEN)
    pdf.set_draw_color(*rgb(GREEN))
    pdf.set_line_width(0.8)
    pdf.line(MARGIN, pdf.get_y() + 2, MARGIN + WIDTH, pdf.get_y() + 2)
    pdf.ln(5)
    pdf.paragraph("  ·  ".join([*report.about, f"отчёт от {report.created}"]),
                  size=9, color=GREY)


def draw_tiles(pdf: ReportPdf, tiles: list[tuple[str, str]]) -> None:
    """Рисует главные числа плитками в один ряд."""
    gap, pad = 4, 3.5
    width = (WIDTH - gap * (len(tiles) - 1)) / len(tiles)
    top = pdf.get_y() + 5
    for number, (label, value) in enumerate(tiles):
        left = MARGIN + number * (width + gap)
        pdf.set_fill_color(*rgb(TILE_COLOR))
        pdf.rect(left, top, width, TILE_HEIGHT, style="F",
                 round_corners=True, corner_radius=2)
        pdf.fit_font(label, False, 8, width - 2 * pad)
        pdf.set_text_color(*rgb(GREY))
        pdf.set_xy(left + pad, top + 3)
        pdf.cell(width - 2 * pad, 4, label)
        pdf.fit_font(value, True, 15, width - 2 * pad)
        pdf.set_text_color(*rgb(DARK_GREEN))
        pdf.set_xy(left + pad, top + 8.5)
        pdf.cell(width - 2 * pad, 7, value)
    pdf.set_xy(MARGIN, top + TILE_HEIGHT)


def draw_points(pdf: ReportPdf, title: str,
                points: list[tuple[str, str]]) -> None:
    """Рисует выводы или рекомендации: номер, жирная фраза, пояснение."""
    pdf.keep_together(30)
    pdf.section(title)
    for number, (head, body) in enumerate(points, start=1):
        # Фраза и пояснение не разрываются между страницами.
        pdf.keep_together(
            pdf.paragraph(head, 10, True, indent=MARK_WIDTH, dry_run=True)
            + pdf.paragraph(body, indent=MARK_WIDTH, dry_run=True))
        pdf.mark(str(number), 10)
        pdf.paragraph(head, 10, bold=True, indent=MARK_WIDTH)
        pdf.paragraph(body, indent=MARK_WIDTH)
        pdf.ln(2.5)


def draw_charts(pdf: ReportPdf, report: Report) -> None:
    """Рисует графики с подписями, по два на страницу."""
    for number, chart in enumerate(report.charts):
        text = caption(chart)
        block = IMAGE_HEIGHT + 2 + pdf.paragraph(text, 8.5, dry_run=True)
        # Заголовок раздела не остаётся внизу страницы без графика.
        pdf.keep_together(block + (15 if number == 0 else 0))
        if number == 0:
            pdf.section("Графики")
        top = pdf.get_y()
        # Название графика уже есть на самой картинке.
        pdf.image(chart.path, x=MARGIN + (WIDTH - IMAGE_WIDTH) / 2, y=top,
                  w=IMAGE_WIDTH, h=IMAGE_HEIGHT, keep_aspect_ratio=True)
        pdf.set_y(top + IMAGE_HEIGHT + 2)
        pdf.paragraph(text, 8.5, color=GREY)
        pdf.ln(6)


def draw_journal(pdf: ReportPdf, report: Report) -> None:
    """Рисует журнал: что сделано при чтении и при очистке."""
    # Журнал не делится между страницами, пока помещается на одну: иначе
    # на последней странице остаются две-три строки. 40 мм занимают
    # заголовки и абзац о том, как собран отчёт.
    notes = report.reading + report.cleaning
    pdf.keep_together(40 + sum(
        pdf.paragraph(note, 9, indent=MARK_WIDTH, dry_run=True) + 0.8
        for note in notes))
    pdf.section("Что сделано с данными")
    for title, notes in (("При чтении файла", report.reading),
                         ("При очистке", report.cleaning)):
        if not notes:
            continue
        pdf.keep_together(15)
        pdf.paragraph(title, 9, bold=True)
        pdf.ln(1)
        for note in notes:
            pdf.mark("•", 9)
            pdf.paragraph(note, 9, indent=MARK_WIDTH)
            pdf.ln(0.8)
        pdf.ln(2)
    pdf.ln(1)
    pdf.paragraph(report.how_built, 8.5, color=GREY)


def draw(report: Report, pages: int) -> ReportPdf:
    """Рисует весь отчёт и возвращает его."""
    origin = "  ·  ".join(
        ["Аналитический MCP-сервер", report.source, report.created])
    pdf = ReportPdf(origin, pages)
    pdf.add_page()
    draw_header(pdf, report)
    if report.tiles:
        draw_tiles(pdf, report.tiles)
    draw_points(pdf, "Выводы", report.conclusions)
    draw_points(pdf, "Рекомендации", report.recommendations)
    draw_charts(pdf, report)
    draw_journal(pdf, report)
    return pdf


def write_pdf(report: Report, path: Path) -> int:
    """Сохраняет отчёт в PDF и возвращает число страниц.

    Отчёт рисуется дважды. Первый проход считает страницы, второй пишет
    в колонтитул «страница N из M».
    """
    pages = draw(report, 0).page_no()
    draw(report, pages).output(str(path))
    return pages
