from pathlib import Path
from .common import iter_workbook


def read(path: Path):
    return iter_workbook(path, "systeme")
