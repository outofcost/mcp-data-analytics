"""Пути и режим работы сервера."""

from dataclasses import dataclass, field
from pathlib import Path

# Корень репозитория. Все пути считаются от него: клиент вроде Claude
# Desktop запускает сервер из произвольной папки.
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """Настройки одного экземпляра сервера.

    Attributes:
        root: корень репозитория, от него считаются относительные пути.
        data_dir: папка с файлами данных.
        output_dir: папка, куда сервер пишет графики и отчёты.
        restrict_to_data_dir: читать файлы только из ``data_dir``. Включается
            в режиме HTTP: адрес сервера публичный, и без ограничения любой,
            кто его знает, прочитал бы произвольный файл на машине.
        open_report: открывать готовый отчёт на этой машине. Включается
            переменной ANALYTICS_OPEN_REPORT=1 при локальном запуске.
        public_url: адрес сервера в режиме HTTP. Если задан, save_report
            возвращает ссылку на отчёт.
        report_links: ключ из ссылки → файл отчёта. Ключ случайный, поэтому
            чужой отчёт перебором не открыть.
    """

    root: Path = ROOT
    data_dir: Path = ROOT / "data"
    output_dir: Path = ROOT / "output"
    restrict_to_data_dir: bool = False
    open_report: bool = False
    public_url: str = ""
    report_links: dict[str, Path] = field(default_factory=dict)

    def relative(self, path: Path) -> str:
        """Возвращает путь от корня репозитория, если файл лежит в нём."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)
