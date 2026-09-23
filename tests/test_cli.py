import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("date,expected", [("2026-09-01", 0), ("invalid", 1), ("2026-09-02", 1)])
def test_cli(dataset_dir, date, expected):
    result = subprocess.run([
        sys.executable, "-m", "backend.validate_data", "--input", str(dataset_dir),
        "--as-of-date", date, "--history-start", "2026-08-02", "--history-end", "2026-08-31",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == expected, result.stderr
    assert json.loads(result.stdout)["valid"] is (expected == 0)


def test_cli_missing_files(tmp_path):
    result = subprocess.run([
        sys.executable, "-m", "backend.validate_data", "--input", str(tmp_path),
        "--as-of-date", "2026-09-01", "--history-start", "2026-08-02", "--history-end", "2026-08-31",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert any(e["code"] == "MISSING_FILE" for e in json.loads(result.stdout)["errors"])
