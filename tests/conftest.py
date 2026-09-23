import shutil
import tempfile
from pathlib import Path

import pytest

from backend.app.engine.contracts import DatasetContext


def pytest_configure(config):
    # Avoid Windows TEMP directories owned by a different sandbox/user.
    # A fresh run directory also keeps concurrent runs isolated.
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1] / ".test-runs"
        root.mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="run-", dir=root))
        config.option.basetemp = str(run / "tmp")


@pytest.fixture
def context():
    return DatasetContext(as_of_date="2026-09-01", history_start="2026-08-02", history_end="2026-08-31")


@pytest.fixture
def dataset_dir(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "samples" / "minimal"
    target = tmp_path / "dataset"
    shutil.copytree(source, target)
    return target
