"""Скилл очистки: дубликаты, пропуски, написание значений, выбросы.

Главное правило: инструмент сообщает, что он реально сделал, с числами.
Спорное решение (что делать с выбросами) остаётся человеку: по умолчанию
выбросы помечаются и остаются в таблице.
"""

from typing import Annotated, Literal

import pandas as pd
from pydantic import Field

from analytics_mcp import columns as col
from analytics_mcp.models import CleanResult
from analytics_mcp.registry import Skill, register_skill, tool
from analytics_mcp.store import Analysis
from analytics_mcp.style import format_number

# Выбросом считается значение дальше трёх межквартильных размахов
# от квартилей. Это граница «грубых» выбросов: обычные большие продажи
# под неё не попадают.
OUTLIER_FACTOR = 3.0
MIN_ROWS_FOR_OUTLIERS = 8
FILL_CATEGORY = "Не указано"


def normalize_text(frame: pd.DataFrame, roles: dict[str, str]) -> list[str]:
    """Приводит текстовые значения к одному написанию.

    «молочные продукты» и «Молочные продукты» становятся одним значением:
    выбирается написание, которое встречается чаще.
    """
    actions = []
    for name in col.columns_with_role(roles, col.CATEGORY):
        original = frame[name]
        squeezed = original.str.replace(r"\s+", " ", regex=True).str.strip()
        key = squeezed.str.lower()
        best = squeezed.groupby(key).agg(lambda s: s.value_counts().idxmax())
        normalized = key.map(best).astype(original.dtype)
        changed = original.notna() & (original != normalized)
        if changed.any():
            first = changed.idxmax()
            actions.append(
                f"привёл к одному написанию значения в колонке «{name}»: "
                f"{int(changed.sum())} строк (например, «{original[first]}» "
                f"→ «{normalized[first]}»)")
            frame[name] = normalized
    return actions


def fill_gaps(frame: pd.DataFrame, roles: dict[str, str],
              mode: str) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Обрабатывает пропуски и возвращает таблицу, действия и оставленное."""
    actions, untouched = [], []
    checked = [name for name in frame.columns
               if roles[name] in (col.DATE, col.NUMBER, col.CATEGORY)]
    total = int(frame[checked].isna().sum().sum())
    if not total:
        return frame, actions, untouched
    if mode == "none":
        untouched.append(f"Пропуски оставлены как есть: {total}.")
        return frame, actions, untouched
    if mode == "drop":
        keep = frame[checked].notna().all(axis=1)
        actions.append(f"удалил строки с пропусками: {int((~keep).sum())}")
        return frame[keep], actions, untouched

    for name in col.columns_with_role(roles, col.DATE):
        missing = frame[name].isna()
        if missing.any():
            actions.append(f"удалил строки без даты в колонке «{name}»: "
                           f"{int(missing.sum())}")
            frame = frame[~missing]
    for name in col.columns_with_role(roles, col.NUMBER):
        missing = int(frame[name].isna().sum())
        if missing:
            median = frame[name].median()
            frame[name] = frame[name].fillna(median)
            actions.append(f"заполнил пропуски в колонке «{name}» медианой "
                           f"{format_number(median)}: {missing}")
    for name in col.columns_with_role(roles, col.CATEGORY):
        missing = int(frame[name].isna().sum())
        if missing:
            frame[name] = frame[name].fillna(FILL_CATEGORY)
            actions.append(f"заполнил пропуски в колонке «{name}» значением "
                           f"«{FILL_CATEGORY}»: {missing}")
    return frame, actions, untouched


def find_outliers(frame: pd.DataFrame,
                  roles: dict[str, str]) -> tuple[pd.Series, list[dict]]:
    """Ищет грубые выбросы в числовых колонках по межквартильному размаху."""
    mask = pd.Series(False, index=frame.index)
    found = []
    for name in col.columns_with_role(roles, col.NUMBER):
        values = frame[name].dropna()
        if len(values) < MIN_ROWS_FOR_OUTLIERS:
            continue
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        spread = q3 - q1
        if spread == 0:
            continue
        low, high = q1 - OUTLIER_FACTOR * spread, q3 + OUTLIER_FACTOR * spread
        outside = (frame[name] < low) | (frame[name] > high)
        if outside.any():
            examples = frame.loc[outside, name].sort_values(ascending=False)
            found.append({
                "column": name,
                "count": int(outside.sum()),
                "lower_bound": round(float(low), 2),
                "upper_bound": round(float(high), 2),
                "examples": [round(float(v), 2) for v in examples.head(3)],
                # Во сколько раз пример больше верхней границы: помогает
                # отличить опечатку от просто крупного значения.
                "examples_times_upper_bound": [
                    round(float(v / high), 1) for v in examples.head(3)
                ] if high > 0 else [],
            })
            mask |= outside
    return mask, found


@register_skill
class DataCleaningSkill(Skill):
    """Этап 2. Чистит данные и отчитывается о каждом действии."""

    stage = 20
    title = "Очистка"
    guide = ("Убирает дубликаты, заполняет пропуски, приводит написание "
             "значений к одному виду, помечает выбросы. Сообщает, что "
             "сделано, с числами.")

    def is_done(self, analysis: Analysis) -> bool:
        """Этап выполнен, когда появилась очищенная таблица."""
        return analysis.clean_id is not None

    def hint(self, analysis: Analysis) -> str:
        """Подсказывает запустить очистку исходной таблицы."""
        return f"Вызовите clean_data(dataset_id=\"{analysis.root_id}\")."

    @tool
    def clean_data(
        self,
        dataset_id: Annotated[str, Field(
            description="Идентификатор таблицы из ответа load_data")],
        drop_duplicates: Annotated[bool, Field(
            description="Удалять полностью повторяющиеся строки")] = True,
        fill_missing: Annotated[Literal["auto", "drop", "none"], Field(
            description="Пропуски: auto заполняет числа медианой, "
                        "категории значением «Не указано» и удаляет строки "
                        "без даты; drop удаляет строки с пропусками; none "
                        "оставляет как есть")] = "auto",
        outliers: Annotated[Literal["flag", "remove", "none"], Field(
            description="Выбросы: flag помечает строки и исключает их из "
                        "графиков и итогов, строки остаются в таблице; "
                        "remove удаляет строки; none не ищет выбросы")
        ] = "flag",
    ) -> CleanResult:
        """Чистит таблицу и сообщает, что именно сделано, с числами.

        Удаляет пустые колонки и дубликаты, приводит написание категорий
        к одному виду, обрабатывает пропуски, ищет грубые выбросы (дальше
        трёх межквартильных размахов от квартилей). Исходная таблица не
        меняется: результат сохраняется под новым dataset_id.
        """
        dataset = self.store.get(dataset_id)
        analysis = dataset.analysis
        frame, roles = dataset.frame.copy(), dict(dataset.roles)
        frame = frame.drop(columns=[col.OUTLIER_COLUMN], errors="ignore")
        roles.pop(col.OUTLIER_COLUMN, None)
        rows_before = len(frame)
        actions, untouched = [], []

        empty = col.columns_with_role(roles, col.EMPTY)
        if empty:
            frame = frame.drop(columns=empty)
            roles = {name: role for name, role in roles.items()
                     if name not in empty}
            actions.append(f"удалил пустые колонки: {', '.join(empty)}")

        actions += normalize_text(frame, roles)

        duplicates = int(frame.duplicated().sum())
        if duplicates and drop_duplicates:
            frame = frame.drop_duplicates()
            actions.append(f"удалил полные дубликаты строк: {duplicates}")
        elif duplicates:
            untouched.append(f"Дубликаты оставлены: {duplicates}.")

        frame, gap_actions, gap_untouched = fill_gaps(frame, roles,
                                                      fill_missing)
        actions += gap_actions
        untouched += gap_untouched

        found = []
        if outliers != "none":
            mask, found = find_outliers(frame, roles)
            count = int(mask.sum())
            if count and outliers == "remove":
                frame = frame[~mask]
                actions.append(f"удалил строки с выбросами: {count}")
            elif count:
                frame[col.OUTLIER_COLUMN] = mask
                roles[col.OUTLIER_COLUMN] = col.FLAG
                actions.append(
                    f"пометил строки с выбросами: {count}. Они остались в "
                    f"таблице (колонка {col.OUTLIER_COLUMN}), но в графики "
                    "и итоги не входят")
                untouched.append(
                    "Выбросы помечены, решение за человеком: это ошибка "
                    "ввода или настоящие значения. clean_data с "
                    "outliers=\"remove\" удалит строки, с outliers=\"none\" "
                    "вернёт их в расчёт.")

        if not actions:
            actions.append("дубликатов, пропусков и выбросов не нашёл, "
                           "таблица не менялась")
        if analysis.charts or analysis.findings:
            analysis.charts, analysis.findings = [], None
            analysis.report_path = None
            actions.append("графики и итоги, построенные до этой очистки, "
                           "сбросил: постройте их заново")

        clean = self.store.derive(dataset, frame.reset_index(drop=True),
                                  roles, "clean")
        analysis.clean_id = clean.dataset_id
        analysis.cleaning_log = list(actions)
        return CleanResult(
            dataset_id=clean.dataset_id,
            rows_before=rows_before,
            rows_after=len(frame),
            actions=actions,
            outliers=found,
            untouched=untouched,
            next_step=self.next_step(clean),
        )
