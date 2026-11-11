"""Сборка PDF из текста отчёта.

``save_report`` собирает отчёт строками Markdown. Этот модуль читает те же
строки и рисует по ним PDF с графиками внутри: один файл, который
открывается на телефоне и уходит в мессенджер. Содержание у Markdown и PDF
одно, разойтись они не могут.

Разметка отчёта простая, её пишет сам сервер: заголовки трёх уровней,
списки, нумерованные пункты, картинки и обычные абзацы.
"""

import logging
import re
from pathlib import Path

import matplotlib
from fpdf import FPDF

from analytics_mcp.style import DARK_GREEN, GREEN, GREY, TEXT

# Шрифт с кириллицей идёт в комплекте с matplotlib, отдельно его не ставим.
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
FONT = "DejaVu"
IMAGE = re.compile(r"!\[.*\]\((.+)\)$")
BULLET = re.compile(r"( *)- (.+)")
IMAGE_WIDTH = 160       # мм, ширина графика на странице
CHART_BLOCK = 100       # мм: столько места на странице нужно графику
INDENT = 5              # мм, отступ одного уровня списка

# Библиотека шрифтов пишет в журнал каждую вставку шрифта, это шум.
logging.getLogger("fontTools").setLevel(logging.WARNING)


def rgb(color: str) -> tuple[int, int, int]:
    """Переводит цвет вида #2DBE64 в три числа."""
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def plain(text: str) -> str:
    """Убирает из строки разметку Markdown: жирный и обратные кавычки."""
    return text.replace("**", "").replace("`", "")


class ReportPdf(FPDF):
    """Страница отчёта: шрифт с кириллицей и номер страницы внизу."""

    def __init__(self) -> None:
        """Подключает шрифт и задаёт поля."""
        super().__init__(format="A4")
        self.add_font(FONT, "", FONT_DIR / "DejaVuSans.ttf")
        self.add_font(FONT, "B", FONT_DIR / "DejaVuSans-Bold.ttf")
        self.set_margins(20, 18, 20)
        self.set_auto_page_break(True, margin=18)

    def footer(self) -> None:
        """Пишет номер страницы."""
        self.set_y(-13)
        self.set_font(FONT, "", 8)
        self.set_text_color(*rgb(GREY))
        self.cell(0, 8, str(self.page_no()), align="C")

    def paragraph(self, text: str, size: float = 10, bold: bool = False,
                  color: str = TEXT, indent: float = 0) -> None:
        """Пишет абзац с переносом строк и отступом слева."""
        self.set_font(FONT, "B" if bold else "", size)
        self.set_text_color(*rgb(color))
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, size * 0.5, plain(text), align="L",
                        new_x="LMARGIN", new_y="NEXT")


def write_pdf(lines: list[str], folder: Path, path: Path) -> None:
    """Рисует PDF по строкам отчёта и сохраняет его в ``path``.

    Args:
        lines: строки отчёта в Markdown, как их собрал ``save_report``.
        folder: папка с графиками, на которые ссылаются строки.
        path: куда сохранить PDF.
    """
    pdf = ReportPdf()
    pdf.add_page()
    for line in lines:
        image = IMAGE.match(line)
        bullet = BULLET.match(line)
        if not line.strip():
            pdf.ln(2)
        elif line.startswith("# "):
            pdf.set_title(plain(line[2:]))
            pdf.paragraph(line[2:], size=18, bold=True, color=DARK_GREEN)
            pdf.set_draw_color(*rgb(GREEN))
            pdf.set_line_width(0.8)
            pdf.line(pdf.l_margin, pdf.get_y() + 2,
                     pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(4)
        elif line.startswith("## "):
            pdf.ln(3)
            pdf.paragraph(line[3:], size=13, bold=True, color=DARK_GREEN)
        elif line.startswith("### "):
            # Заголовок третьего уровня стоит перед графиком. В PDF его не
            # печатаем: название уже есть на самой картинке. Если график
            # не помещается на странице, начинаем новую.
            if pdf.will_page_break(CHART_BLOCK):
                pdf.add_page()
        elif image:
            pdf.image(folder / image.group(1), w=IMAGE_WIDTH,
                      x=(pdf.w - IMAGE_WIDTH) / 2)
            pdf.ln(2)
        elif bullet:
            depth = len(bullet.group(1)) // 2
            pdf.paragraph("• " + bullet.group(2), size=10 if not depth else 9,
                          indent=INDENT * depth)
        else:
            pdf.paragraph(line)
    pdf.output(str(path))
