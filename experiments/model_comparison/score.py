"""Считает метрики сравнения моделей по журналам прогонов.

Читает папки runs/<код прогона>/ (их пишет run_models.py), считает метрики
из protocol.md и применяет записанное там правило решения. Печатает итог
и сохраняет его в results.md.

Запуск из корня репозитория:
    python experiments/model_comparison/score.py
"""

import argparse
import json
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
STAGES = {
    "list_data_files": 1, "load_data": 1, "describe_data": 1,
    "clean_data": 2,
    "suggest_charts": 3, "plot_trend": 3, "plot_distribution": 3,
    "correlation_analysis": 3,
    "collect_findings": 4, "save_report": 4,
}
CHART_TOOLS = {"plot_trend", "plot_distribution", "correlation_analysis"}
PATTERN_FILE = "data/sales_data.csv"
GROWTH = ("рост", "раст", "вырос", "прирост", "увелич", "быстр")
LOSS = ("убыт", "отрицательн", "минус")
WEAK_MODEL = "mistralai/mistral-nemo"


def read_run(folder: Path) -> dict:
    """Читает файлы одного прогона: meta, записи журнала и ответ модели."""
    log = folder / "console-log.txt"
    answer = folder / "answer.md"
    return {
        "meta": json.loads((folder / "meta.json").read_text("utf-8")),
        "records": [json.loads(line) for line
                    in log.read_text("utf-8").splitlines()]
        if log.exists() else [],
        "answer": answer.read_text("utf-8") if answer.exists() else "",
    }


def chart_key(call: dict) -> str:
    """Возвращает признак графика: инструмент и аргументы без dataset_id."""
    arguments = {key: value for key, value in call["arguments"].items()
                 if key != "dataset_id"}
    return call["tool"] + json.dumps(arguments, sort_keys=True,
                                     ensure_ascii=False)


def count_patterns(text: str) -> int:
    """Считает, сколько из трёх заложенных закономерностей названо."""
    lines = text.lower().splitlines()
    season = any("декабр" in line for line in lines)
    growth = any("казан" in line and any(word in line for word in GROWTH)
                 for line in lines)
    loss = any("готов" in line and "обед" in line
               and any(word in line for word in LOSS) for line in lines)
    return season + growth + loss


def as_text(value) -> str:
    """Склеивает аргумент save_report (список строк или строку) в текст."""
    return "\n".join(value) if isinstance(value, list) else str(value or "")


def score_run(run: dict) -> dict:
    """Считает метрики одного прогона по правилам из protocol.md."""
    meta, records = run["meta"], run["records"]
    calls = [record for record in records if record["event"] == "tool_call"]
    good = [call for call in calls if not call["is_error"]]
    names = [call["tool"] for call in good]

    charts = {chart_key(call) for call in good if call["tool"] in CHART_TOOLS}
    first_chart = next((index for index, name in enumerate(names)
                        if name in CHART_TOOLS), len(names))
    after_listing = [name for name in names if name != "list_data_files"]
    last_report = (len(names) - 1 - names[::-1].index("save_report")
                   if "save_report" in names else -1)

    conditions = [
        meta["status"] == "ok",
        bool(after_listing) and after_listing[0] == "load_data"
        and all(name == "list_data_files"
                for name in names[:names.index("load_data")]),
        "clean_data" in names and names.index("clean_data") < first_chart,
        len(charts) >= 3,
        last_report >= 0 and last_report == len(names) - 1
        and "collect_findings" in names[:last_report],
    ]
    stages = [STAGES[name] for name in names if name in STAGES]
    errors = [index for index, call in enumerate(calls) if call["is_error"]]
    fixed = sum(
        any(not later["is_error"] and later["tool"] == calls[index]["tool"]
            for later in calls[index + 1:])
        for index in errors
    )

    patterns = None
    if meta["file"] == PATTERN_FILE:
        text = run["answer"]
        if last_report >= 0:
            arguments = good[last_report]["arguments"]
            text += "\n" + as_text(arguments.get("conclusions"))
            text += "\n" + as_text(arguments.get("recommendations"))
        patterns = count_patterns(text)

    return {
        "run": meta["run"],
        "model": meta["model"],
        "file": meta["file"],
        "status": meta["status"],
        "chain": all(conditions),
        "failed": [number for number, passed
                   in enumerate(conditions, start=1) if not passed],
        "report": "save_report" in names,
        "ordered": stages == sorted(stages),
        "charts": len(charts),
        "calls": len(calls),
        "errors": len(errors),
        "fixed": fixed,
        "patterns": patterns,
        "cost": meta["cost_usd"],
        "seconds": meta["seconds"],
    }


def load_scores(runs_dir: Path) -> tuple[list[dict], list[str]]:
    """Считает все прогоны. Прогон с повтором заменяется своим повтором."""
    folders = {folder.name: folder for folder in sorted(runs_dir.iterdir())
               if (folder / "meta.json").exists()}
    replaced = [name for name in folders if f"{name}__retry" in folders]
    scores = [score_run(read_run(folder)) for name, folder in folders.items()
              if name not in replaced]
    return scores, replaced


def yes(flag: bool) -> str:
    """Пишет признак словом для таблицы."""
    return "да" if flag else "нет"


def chain_verdict(held: int, total: int) -> str:
    """Применяет правило протокола к числу выдержанных цепочек из шести."""
    if total < 6:
        return f"не решено: прогонов {total} из 6"
    if held >= 5:
        return "порядок держится"
    return "порядок не держится" if held <= 3 else "не решено"


def summarize(model: str, rows: list[dict]) -> dict:
    """Сводит прогоны одной модели в строку итоговой таблицы."""
    sales = [row for row in rows if row["patterns"] is not None]
    meaningful = sum(row["patterns"] >= 2 for row in sales)
    held = sum(row["chain"] for row in rows)
    if len(sales) < 3:
        insight = f"не решено: прогонов {len(sales)} из 3"
    else:
        insight = ("выводы осмысленные" if meaningful >= 2
                   else "выводы слабые")
    return {
        "model": model,
        "runs": len(rows),
        "held": held,
        "verdict": chain_verdict(held, len(rows)),
        "api_failures": sum(row["status"] == "error" for row in rows),
        "reports": sum(row["report"] for row in rows),
        "ordered": sum(row["ordered"] for row in rows),
        "charts": mean(row["charts"] for row in rows),
        "calls": mean(row["calls"] for row in rows),
        "errors": sum(row["errors"] for row in rows),
        "fixed": sum(row["fixed"] for row in rows),
        "patterns": ", ".join(str(row["patterns"]) for row in sales),
        "meaningful": meaningful,
        "sales_runs": len(sales),
        "insight": insight,
        "cost": mean(row["cost"] for row in rows),
        "seconds": mean(row["seconds"] for row in rows),
    }


def overall(summaries: list[dict]) -> list[str]:
    """Формулирует общий вывод по правилу из protocol.md."""
    holds = {item["model"]: item["verdict"] == "порядок держится"
             for item in summaries}
    fails = {item["model"]: item["verdict"] == "порядок не держится"
             for item in summaries}
    others = [model for model in holds if model != WEAK_MODEL]
    if all(holds.values()):
        first = ("Порядок держится на всех моделях: первая часть гипотезы "
                 "подтверждена.")
    elif all(holds[model] for model in others) and fails.get(WEAK_MODEL):
        first = (f"Порядок держится на трёх моделях и не держится на "
                 f"{WEAK_MODEL}: порядок зависит от модели, серверной "
                 "подсказки слабой модели не хватает.")
    else:
        first = ("Первая часть гипотезы не подтверждена: расклад по моделям "
                 "в таблице.")
    strong = {item["model"]: item["insight"] == "выводы осмысленные"
              for item in summaries}
    weak = {item["model"]: item["insight"] == "выводы слабые"
            for item in summaries}
    if weak.get(WEAK_MODEL) and all(strong[model] for model in others):
        second = (f"Выводы у {WEAK_MODEL} слабые, у остальных осмысленные: "
                  "вторая часть гипотезы подтверждена.")
    else:
        second = ("Вторая часть гипотезы не подтверждена: различия в "
                  "качестве выводов между слабой моделью и остальными "
                  "эксперимент не показал.")
    return [first, second]


def build_report(scores: list[dict], replaced: list[str],
                 addition: bool = False) -> str:
    """Собирает итог в Markdown: сводка по моделям, вывод, все прогоны.

    С addition=True это серия, проведённая после протокола: общий вывод
    по правилу протокола к ней не применяется.
    """
    models = list(dict.fromkeys(row["model"] for row in scores))
    summaries = [summarize(model, [row for row in scores
                                   if row["model"] == model])
                 for model in models]
    total_cost = sum(row["cost"] for row in scores)
    lines = [
        "# Результаты сравнения моделей",
        "",
        "Файл собрал `score.py` по журналам прогонов. Правила подсчёта "
        "и решения записаны в `protocol.md` до прогонов.",
        "",
        f"Прогонов в подсчёте: {len(scores)}. Расход по ним: "
        f"{total_cost:.3f} $.",
        "",
        "## Итог по моделям",
        "",
        "| Модель | Цепочка выдержана | Решение | Сорвано сбоем API | Отчёт "
        "сохранён | Этапы по порядку | Графиков в среднем | Вызовов "
        "в среднем | Ошибок / исправлено | Закономерностей из 3 "
        "(sales_data) | Осмысленных выводов | Решение по выводам | Цена "
        "прогона, $ | Время, с |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in summaries:
        lines.append(
            f"| `{item['model']}` | {item['held']} из {item['runs']} | "
            f"{item['verdict']} | {item['api_failures']} из {item['runs']} | "
            f"{item['reports']} из {item['runs']} | "
            f"{item['ordered']} из {item['runs']} | {item['charts']:.1f} | "
            f"{item['calls']:.1f} | {item['errors']} / {item['fixed']} | "
            f"{item['patterns']} | {item['meaningful']} из "
            f"{item['sales_runs']} | {item['insight']} | "
            f"{item['cost']:.4f} | {item['seconds']:.0f} |"
        )
    lines += ["", "## Вывод по правилу протокола", ""]
    if addition:
        lines.append(
            "- Это дополнительная серия, проведённая после протокола. "
            "Общий вывод по правилу протокола к ней не применяется, "
            "решение по модели считается по тому же правилу.")
    else:
        lines += [f"- {sentence}" for sentence in overall(summaries)]
    lines += [
        "", "## Все прогоны", "",
        "Колонка «Не выполнено» называет номера условий цепочки из "
        "`protocol.md`: 1 статус, 2 первым `load_data`, 3 очистка до "
        "графиков, 4 три графика, 5 отчёт последним после "
        "`collect_findings`.",
        "",
        "| Прогон | Статус | Цепочка | Не выполнено | Отчёт | По порядку "
        "| Графиков | Вызовов | Ошибок / исправлено | Закономерностей "
        "| Цена, $ | Время, с |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in scores:
        patterns = "" if row["patterns"] is None else row["patterns"]
        failed = ", ".join(map(str, row["failed"]))
        lines.append(
            f"| `{row['run']}` | {row['status']} | {yes(row['chain'])} | "
            f"{failed} | {yes(row['report'])} | {yes(row['ordered'])} | "
            f"{row['charts']} | {row['calls']} | {row['errors']} / "
            f"{row['fixed']} | {patterns} | {row['cost']:.4f} | "
            f"{row['seconds']:.0f} |"
        )
    if replaced:
        lines += ["", "## Прогоны, заменённые повтором после сбоя API", ""]
        lines += [f"- `{name}`" for name in replaced]
    return "\n".join(lines) + "\n"


def main() -> None:
    """Считает метрики, печатает итог и пишет results.md."""
    parser = argparse.ArgumentParser(
        description="Подсчёт метрик сравнения моделей"
    )
    parser.add_argument("--runs-dir", type=Path, default=HERE / "runs")
    parser.add_argument("--out", type=Path, default=HERE / "results.md")
    parser.add_argument("--addition", action="store_true",
                        help="серия после протокола: без общего вывода")
    args = parser.parse_args()

    scores, replaced = load_scores(args.runs_dir)
    if not scores:
        raise SystemExit(f"В {args.runs_dir} нет прогонов с meta.json.")
    report = build_report(scores, replaced, args.addition)
    args.out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
