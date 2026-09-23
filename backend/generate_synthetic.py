"""Generate canonical CSVs and isolated evaluation truth, then validate them."""

import argparse
import json
import sys
from pathlib import Path

from backend.app.engine.contracts import parse_date
from backend.synthetic.generator import DEFAULT_END, DEFAULT_START, GenerationConfig, generate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-date", default=DEFAULT_START.isoformat())
    parser.add_argument("--end-date", default=DEFAULT_END.isoformat())
    args = parser.parse_args()
    try:
        config = GenerationConfig(seed=args.seed, start_date=parse_date(args.start_date), end_date=parse_date(args.end_date))
        summary = generate_dataset(args.output, config)
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
