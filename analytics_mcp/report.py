"""Отчёт: проверка выводов модели перед сборкой.

Форму отчёта задаёт сервер. Модель присылает выводы и рекомендации
объектами (короткая фраза и пояснение с цифрой), сервер проверяет их по
правилам из этого файла. Поэтому отчёт выглядит одинаково у любой модели.
"""

import re

# Границы из описаний Conclusion и Recommendation в models.py.
CONCLUSIONS = (3, 5)        # сколько выводов в отчёте
RECOMMENDATIONS = (2, 4)    # сколько рекомендаций
HEADLINE_WORDS = 8
ACTION_WORDS = 10
BODY_CHARS = 180


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
