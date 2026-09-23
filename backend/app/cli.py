"""CLI for file diagnostics, PostgreSQL imports and frozen-dataset previews."""
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
    calculation.add_argument("--dataset", help="Read a frozen PostgreSQL dataset instead of Excel")
    iek = sub.add_parser("preview-iek", help="IEK scenario with explicit stock and unit assumptions")
    iek.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    iek.add_argument("--policy", type=Path, required=True)
    iek.add_argument("--output", type=Path)
    iek.add_argument("--dataset", help="Read an explicit frozen IEK dataset instead of Excel")
    demo = sub.add_parser("engine-demo", help="Reproducible synthetic demand scenarios, without a database")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--output", type=Path)
    sub.add_parser("db-upgrade", help="Apply Alembic migrations to DATABASE_URL")
    ingest = sub.add_parser("import-file", help="Persist one workbook without activating it")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--supplier", choices=["iek", "systeme"], required=True)
    ingest.add_argument("--context", type=Path, help="Optional explicit source context JSON")
    bulk = sub.add_parser("import-all", help="Persist repository source books with unconfirmed context")
    bulk.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    sub.add_parser("imports", help="List persisted imports and counts")
    diagnostics = sub.add_parser("import-issues", help="Paginated validation diagnostics")
    diagnostics.add_argument("id")
    diagnostics.add_argument("--limit", type=int, default=100)
    diagnostics.add_argument("--offset", type=int, default=0)
    activation = sub.add_parser("dataset-create", help="Activate an explicit immutable source manifest")
    activation.add_argument("manifest", type=Path)
    show = sub.add_parser("dataset-show")
    show.add_argument("id")
    data = sub.add_parser("dataset-rows", help="Read accepted source rows from PostgreSQL, without Excel")
    data.add_argument("id")
    data.add_argument("--role", required=True)
    data.add_argument("--limit", type=int, default=100)
    data.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    root = getattr(args, "root", Path(__file__).resolve().parents[2]).resolve()
    if args.command == "profile":
        result = profile_sources(root, args.output or root / "data/cache/profile")
        print(f'Completed {len(result["files"])} files in {result["elapsed_seconds"]} s')
    elif args.command == "engine-demo":
        from .modules.calculations.synthetic import run_demo
        result = run_demo(args.output or root / "data/cache/engine-demo.json", args.seed)
        print(f'Synthetic scenarios: {len(result["recommendations"])}; JSON, HTML and diagnostic CSV written')
    elif args.command == "preview-iek":
        from .modules.calculations.iek_preview import preview_iek
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        persisted = None
        if args.dataset:
            from .db.session import get_engine
            from .modules.imports.datasets import iek_preview_sources
            engine = get_engine()
            try:
                persisted, dataset = iek_preview_sources(engine, args.dataset)
            finally:
                engine.dispose()
        result = preview_iek(root, policy, args.output or root / "data/cache/iek-preview.json", persisted, args.dataset)
        print(dict(Counter(r["status"] for r in result["recommendations"])))
    elif args.command == "preview-systeme":
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        persisted = None
        if args.dataset:
            from .db.session import get_engine
            from .modules.imports.datasets import systeme_preview_sources
            engine = get_engine()
            try:
                persisted, dataset = systeme_preview_sources(engine, args.dataset)
                context = dataset["manifest"]["sources"]["systeme:sales"]["context"]
                if context.get("snapshot_date") and context["snapshot_date"] != policy["assumed_stock_date"]:
                    raise ValueError("Scenario stock date conflicts with dataset metadata")
                if context.get("inbound_year") and context["inbound_year"] != int(policy["inbound_date"][:4]):
                    raise ValueError("Scenario inbound year conflicts with dataset metadata")
            finally:
                engine.dispose()
        result = preview(root, policy, args.output or root / "data/cache/systeme-preview.json", persisted, args.dataset)
        print(dict(Counter(r["status"] for r in result["recommendations"])))
    else:
        run_storage(args, root)


def run_storage(args, root):
    from .core.config import upload_dir
    from .db.session import get_engine
    from .db.repositories import ImportRepository, DatasetRepository
    from .modules.imports.service import import_file
    from .modules.imports.datasets import create_dataset
    from .modules.imports.profiling import dumps
    if args.command == "db-upgrade":
        from alembic.config import Config
        from alembic import command
        command.upgrade(Config(str(root / "backend/alembic.ini")), "head")
        print("Database upgraded to head")
        return
    engine = get_engine()
    try:
        if args.command in {"import-file", "import-all"}:
            if args.command == "import-file":
                paths = [(args.path, args.supplier)]
                context = json.loads(args.context.read_text(encoding="utf-8")) if args.context else {}
            else:
                paths = [(path, supplier) for folder, supplier in (("IEK", "iek"), ("Systeme electric", "systeme"))
                         for path in sorted((root / folder).glob("*.xlsx"))]
                if not paths:
                    raise ValueError("No source workbooks found")
                context = {}
            failed = False
            for path, supplier in paths:
                result = import_file(engine, path, supplier, upload_dir(), context)
                print(dumps({k: result[k] for k in ("id", "original_name", "status", "reused", "counts")}), flush=True)
                failed |= result["status"] == "failed"
            if failed:
                raise SystemExit(1)
        elif args.command == "dataset-create":
            result = create_dataset(engine, json.loads(args.manifest.read_text(encoding="utf-8")))
            print(dumps(result))
        else:
            if getattr(args, "limit", 100) not in range(1, 1001) or getattr(args, "offset", 0) < 0:
                raise ValueError("limit must be 1..1000 and offset nonnegative")
            with engine.connect() as connection:
                if args.command == "imports":
                    result = ImportRepository(connection).list()
                elif args.command == "import-issues":
                    result = ImportRepository(connection).diagnostics(args.id, args.limit, args.offset)
                elif args.command == "dataset-show":
                    result = DatasetRepository(connection).get(args.id)
                elif args.command == "dataset-rows":
                    result = DatasetRepository(connection).rows(args.id, args.role, args.limit, args.offset)
                print(dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
