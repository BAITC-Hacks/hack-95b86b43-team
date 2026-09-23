import shutil
from pathlib import Path

import pytest

from backend.app.engine.contracts import DatasetContext


@pytest.fixture
def context():
    return DatasetContext(as_of_date="2026-09-01", history_start="2026-08-02", history_end="2026-08-31")


@pytest.fixture
def dataset_dir(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "samples" / "minimal"
    target = tmp_path / "dataset"
    shutil.copytree(source, target)
    return target
