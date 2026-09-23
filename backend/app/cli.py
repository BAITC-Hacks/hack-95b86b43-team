"""Developer entry points; no database or HTTP service required for auditing."""
import argparse
import json
from collections import Counter
from pathlib import Path

from .modules.imports.profiling import profile_sources
from .modules.calculations.preview import preview


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("profile", help="Read every source workbook and write local audit/cache")
    audit.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    audit.add_argument("--output", type=Path)
    calculation = sub.add_parser("preview-systeme", help="Diagnostic scenario, not an approved purchase order")
    calculation.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    calculation.add_argument("--policy", type=Path, required=True)
    calculation.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "profile":
        result = profile_sources(root, args.output or root / "data/cache/profile")
        print(f'Completed {len(result["files"])} files in {result["elapsed_seconds"]} s')
    elif args.command == "preview-systeme":
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        result = preview(root, policy, args.output or root / "data/cache/systeme-preview.json")
        print(dict(Counter(r["status"] for r in result["recommendations"])))


if __name__ == "__main__":
    main()
