"""Пути и режим работы сервера."""

from dataclasses import dataclass
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
    """

    root: Path = ROOT
    data_dir: Path = ROOT / "data"
    output_dir: Path = ROOT / "output"
    restrict_to_data_dir: bool = False

    def relative(self, path: Path) -> str:
        """Возвращает путь от корня репозитория, если файл лежит в нём."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)
