import json
import subprocess
import sys


def command(source, output):
    return [sys.executable, "-m", "backend.preprocess_sales", "--input", str(source), "--output", str(output),
            "--history-start", "2026-08-02", "--history-end", "2026-08-31", "--as-of-date", "2026-09-01"]


def test_cli_exports_separately(dataset_dir, tmp_path):
    original = (dataset_dir / "sales.csv").read_bytes()
    output = tmp_path / "prepared"
    result = subprocess.run(command(dataset_dir, output), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["processed_rows"] == 30
    assert {p.name for p in output.iterdir()} == {"summary.json", "daily_demand.csv", "normalized_sales.jsonl", "customer_events.jsonl"}
    assert (dataset_dir / "sales.csv").read_bytes() == original


def test_cli_rejects_invalid_input(dataset_dir, tmp_path):
    (dataset_dir / "stockouts.csv").unlink()
    result = subprocess.run(command(dataset_dir, tmp_path / "out"), text=True, capture_output=True)
    assert result.returncode == 1
    assert not json.loads(result.stderr)["valid"]
    assert not (tmp_path / "out").exists()


def test_cli_refuses_to_write_into_source(dataset_dir):
    result = subprocess.run(command(dataset_dir, dataset_dir), text=True, capture_output=True)
    assert result.returncode == 1
    assert "separate" in json.loads(result.stderr)["error"]
