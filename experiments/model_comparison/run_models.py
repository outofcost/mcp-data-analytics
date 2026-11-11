"""Прогоняет один запрос на нескольких моделях и сохраняет журналы.

Условия эксперимента записаны в protocol.md до первого прогона. Скрипт
вызывает ту же функцию run_analysis, что консольный клиент и бот, и для
каждого прогона кладёт в runs/<код прогона>/:

* console-log.txt: журнал вызовов инструментов;
* answer.md: итоговый ответ модели;
* report.md: отчёт, который собрал сервер (если модель дошла до него);
* meta.json: модель, файл, статус, время и стоимость.

Запуск из корня репозитория, ключ OpenRouter лежит в .env:
    python experiments/model_comparison/run_models.py

Готовый прогон скрипт пропускает, поэтому после обрыва его можно запустить
снова. Таблицу по журналам считает score.py.
"""

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUEST = "Проанализируй продажи, построй графики и дай рекомендации"
MODELS = [
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3.7-flash",
    "openai/gpt-6.1-terra",
    "mistralai/mistral-nemo",
]
FILES = ["data/sales_data.csv", "data/orders_dirty.xlsx"]
REPEATS = 3
BUDGET_USD = 0.9


def run_code(model: str, file: str, repeat: int) -> str:
    """Собирает код прогона: модель, файл и номер повтора."""
    name = re.sub(r"[^a-z0-9.]+", "-", model.split("/")[-1].lower())
    return f"{name}__{Path(file).stem}__{repeat}"


def read_usage(log_path: Path) -> dict:
    """Достаёт токены и стоимость из последней записи журнала."""
    if not log_path.exists():
        return {}
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1]).get("usage", {}) if lines else {}


def run_once(run_analysis, repo: Path, work_dir: Path, runs_dir: Path,
             code: str, model: str, file: str, repeat: int) -> dict:
    """Проводит один прогон и сохраняет его файлы. Возвращает meta."""
    output_dir = work_dir / code
    started = time.monotonic()
    report, error = None, ""
    try:
        result = asyncio.run(run_analysis(
            repo / file, REQUEST, output_dir=output_dir, model=model,
            progress=lambda line: print(f"  {code} {line}", flush=True),
        ))
        status = result.status
        report = result.files[-1] if result.files else None
    except Exception as failure:    # сбой сети или провайдера модели
        status, error = "error", f"{type(failure).__name__}: {failure}"
    seconds = round(time.monotonic() - started, 1)

    target = runs_dir / code
    target.mkdir(parents=True, exist_ok=True)
    for name in ("console-log.txt", "answer.md"):
        if (output_dir / name).exists():
            shutil.copy(output_dir / name, target / name)
    if report and report.exists():
        shutil.copy(report, target / "report.md")

    usage = read_usage(output_dir / "console-log.txt")
    meta = {
        "run": code,
        "model": model,
        "file": file,
        "repeat": repeat,
        "status": status,
        "seconds": seconds,
        "cost_usd": usage.get("cost", 0.0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "error": error[:300],
    }
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def main() -> None:
    """Разбирает аргументы и проводит все прогоны по очереди."""
    parser = argparse.ArgumentParser(
        description="Сравнение моделей на одной цепочке анализа"
    )
    parser.add_argument("--repo", type=Path, default=HERE.parent.parent,
                        help="корень репозитория с клиентом и сервером")
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--files", nargs="+", default=FILES)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--runs-dir", type=Path, default=HERE / "runs",
                        help="куда класть журналы прогонов")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="куда класть графики, по умолчанию "
                             "output/model_comparison в репозитории")
    parser.add_argument("--budget", type=float, default=BUDGET_USD,
                        help="предел расхода в долларах на этот запуск")
    args = parser.parse_args()

    repo = args.repo.resolve()
    work_dir = args.work_dir or repo / "output" / "model_comparison"
    sys.path.insert(0, str(repo / "clients"))
    from console_client import run_analysis  # noqa: E402

    spent = 0.0
    for model in args.models:
        for file in args.files:
            for repeat in range(1, args.repeats + 1):
                code = run_code(model, file, repeat)
                if (args.runs_dir / code / "meta.json").exists():
                    print(f"{code}: уже есть, пропускаю")
                    continue
                if spent >= args.budget:
                    print(f"{code}: не запущен, расход {spent:.3f} $ "
                          f"дошёл до предела {args.budget} $")
                    continue
                meta = run_once(run_analysis, repo, work_dir, args.runs_dir,
                                code, model, file, repeat)
                spent += meta["cost_usd"]
                if meta["status"] == "error":
                    # Сбой инфраструктуры: по протоколу один повтор.
                    print(f"{code}: сбой ({meta['error']}), повторяю")
                    meta = run_once(run_analysis, repo, work_dir,
                                    args.runs_dir, f"{code}__retry", model,
                                    file, repeat)
                    spent += meta["cost_usd"]
                print(f"{code}: {meta['status']}, {meta['seconds']} с, "
                      f"{meta['cost_usd']:.4f} $, всего {spent:.3f} $",
                      flush=True)


if __name__ == "__main__":
    main()
