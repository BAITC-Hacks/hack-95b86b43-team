"""Opt-in tests on an isolated PostgreSQL schema; never reset application tables."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, select, func, text, update
from sqlalchemy.exc import DBAPIError

from app.core.config import database_url
from app.db.models import metadata, imports, source_rows, observations, datasets
from app.db.repositories import DatasetRepository
from app.modules.imports.adapters.common import SourceRow
from app.modules.imports.service import import_file
from app.modules.imports.datasets import create_dataset

BACKEND = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "Set RUN_POSTGRES_TESTS=1 for isolated PostgreSQL tests")
class PostgresImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "test_import_" + uuid4().hex
        url = database_url()
        cls.admin = create_engine(url, hide_parameters=True)
        with cls.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(url, hide_parameters=True, connect_args={"options": f"-csearch_path={cls.schema}"})
        cls.config = Config(str(BACKEND / "alembic.ini"))
        with cls.engine.begin() as connection:
            cls.config.attributes["connection"] = connection
            command.upgrade(cls.config, "head")
            # Round-trip on the empty, test-only schema checks downgrade ordering.
            command.downgrade(cls.config, "base")
            command.upgrade(cls.config, "head")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        assert re.fullmatch(r"test_import_[0-9a-f]{32}", cls.schema)
        with cls.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin.dispose()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "fixture.xlsx"
        self.path.write_bytes(uuid4().bytes)  # Parser is mocked; no real workbook is fabricated.
        self.storage = self.folder / "stored"

    def row(self, number=2, code="001_", quantity=D(10)):
        return SourceRow("fixture.xlsx", "unused", "systeme", "Sheet", number,
                         "sales_monthly", code, {"2026-01-01": quantity})

    def ingest(self, rows=None, context=None):
        with patch("app.modules.imports.service.iter_workbook", side_effect=lambda *_: iter(rows or [self.row()])):
            return import_file(self.engine, self.path, "systeme", self.storage, context)

    def manifest(self, batch, **extra):
        return {"name": "Test dataset", "mode": "scenario", "acknowledge_warnings": True,
                "sources": {"systeme:sales": {"import_id": batch["id"], "kind": "sales_monthly"}}, **extra}

    def test_schema_matches_models(self):
        with self.engine.connect() as connection:
            self.assertEqual(compare_metadata(MigrationContext.configure(connection), metadata), [])

    def test_iek_database_preview_matches_excel_without_reopening(self):
        import json
        from app.modules.calculations.iek_preview import file_sources, preview_iek
        from app.modules.imports.datasets import iek_preview_sources
        root = BACKEND.parent
        if not (root / "IEK").is_dir():
            self.skipTest("Real IEK sources unavailable")
        sources = file_sources(root)
        manifest = {"name": "IEK test", "mode": "scenario", "allow_partial": True,
                    "acknowledge_warnings": True, "sources": {}}
        for role, rows in sources.items():
            batch = import_file(self.engine, root / "IEK" / rows[0].file, "iek", self.storage)
            manifest["sources"]["iek:" + role] = {"import_id": batch["id"], "kind": rows[0].kind}
        dataset = create_dataset(self.engine, manifest)
        policy = json.loads((root / "tests/fixtures/synthetic/iek_preview_policy.json").read_text(encoding="utf-8"))
        expected = preview_iek(root, policy, self.folder / "file.json", sources)
        stored, _ = iek_preview_sources(self.engine, dataset["id"])
        with patch("app.modules.calculations.iek_preview.read", side_effect=AssertionError("Excel reopened")):
            actual = preview_iek(root, policy, self.folder / "db.json", stored, dataset["id"])
        self.assertEqual(actual["recommendations"], expected["recommendations"])

    def test_same_bytes_renamed_reuse_and_context_creates_version(self):
        first = self.ingest()
        self.path = self.path.rename(self.folder / "renamed.xlsx")
        second = self.ingest()
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["reused"])
        new = self.ingest(context={"scope": "another scope"})
        self.assertNotEqual(first["id"], new["id"])

    def test_null_zero_and_signed_exact_quantities(self):
        batch = self.ingest([self.row(2, "001", None), self.row(3, "002", D(0)),
                             self.row(4, "003", D("-0.12345678901234567890"))])
        with self.engine.connect() as connection:
            values = connection.execute(select(source_rows.c.product_code, observations.c.quantity)
                .join(observations).where(source_rows.c.import_id == batch["id"])
                .order_by(source_rows.c.product_code)).all()
        self.assertEqual(values, [("001", None), ("002", D(0)), ("003", D("-0.12345678901234567890"))])

    def test_duplicate_codes_reject_all_occurrences(self):
        batch = self.ingest([self.row(2), self.row(3)])
        self.assertEqual(batch["counts"]["accepted"], 0)
        self.assertEqual(batch["counts"]["observations"], 0)
        self.assertEqual(batch["counts"]["issues"]["error"], 2)

    def test_invalid_duplicate_also_excludes_valid_counterpart(self):
        batch = self.ingest([self.row(2), replace(self.row(3), errors=("Invalid quantity",))])
        self.assertEqual(batch["counts"]["accepted"], 0)
        self.assertEqual(batch["counts"]["observations"], 0)

    def test_context_confirmation_requires_boolean(self):
        with self.assertRaises(ValueError):
            self.ingest(context={"scope_confirmed": "false"})

    def test_mid_import_failure_rolls_back_rows_and_can_retry(self):
        def broken(*_):
            for i in range(501):
                yield self.row(i + 2, str(i))
            raise RuntimeError("private source detail must not be stored")
        with patch("app.modules.imports.service.iter_workbook", side_effect=broken):
            failed = import_file(self.engine, self.path, "systeme", self.storage)
        self.assertEqual(failed["status"], "failed")
        with self.engine.connect() as connection:
            count = connection.scalar(select(func.count()).select_from(source_rows).where(source_rows.c.import_id == failed["id"]))
        self.assertEqual(count, 0)
        retry = self.ingest()
        self.assertEqual(failed["id"], retry["id"])
        self.assertNotEqual(retry["status"], "failed")
        self.assertEqual(retry["counts"]["rows"], 1)

    def test_concurrent_identical_import_is_single_batch(self):
        with patch("app.modules.imports.service.iter_workbook", side_effect=lambda *_: iter([self.row()])):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(import_file, self.engine, self.path, "systeme", self.storage) for _ in range(2)]
                results = [f.result() for f in futures]
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(sorted(r["reused"] for r in results), [False, True])

    def test_activation_requires_warning_and_partial_acknowledgement(self):
        bad = replace(self.row(3, "002"), errors=("Bad quantity",))
        batch = self.ingest([self.row(), bad])
        with self.assertRaises(ValueError):
            create_dataset(self.engine, self.manifest(batch))
        with self.assertRaises(ValueError):
            create_dataset(self.engine, self.manifest(batch, allow_partial=True, acknowledge_warnings=False))
        dataset = create_dataset(self.engine, self.manifest(batch, allow_partial=True))
        with self.engine.connect() as connection:
            self.assertEqual(len(DatasetRepository(connection).rows(dataset["id"], "systeme:sales")), 1)

    def test_dataset_and_completed_import_are_immutable(self):
        batch = self.ingest()
        manifest = self.manifest(batch)
        dataset = create_dataset(self.engine, manifest)
        self.assertEqual(dataset["id"], create_dataset(self.engine, manifest)["id"])
        self.path.write_bytes(uuid4().bytes)
        new = self.ingest([self.row(quantity=D(999))])
        self.assertNotEqual(new["id"], batch["id"])
        with self.engine.connect() as connection:
            rows = DatasetRepository(connection).rows(dataset["id"], "systeme:sales")
            self.assertEqual(rows[0]["fields"]["2026-01-01"], "10")
        for statement in (update(datasets).where(datasets.c.id == dataset["id"]).values(name="changed"),
                          update(imports).where(imports.c.id == batch["id"]).values(status="loading"),
                          update(source_rows).where(source_rows.c.import_id == batch["id"]).values(accepted=False)):
            with self.assertRaises(DBAPIError):
                with self.engine.begin() as connection:
                    connection.execute(statement)

    def test_unconfirmed_inputs_cannot_be_real_dataset(self):
        batch = self.ingest()
        with self.assertRaises(ValueError):
            create_dataset(self.engine, self.manifest(batch, mode="real"))
        synthetic = self.ingest(context={"synthetic": True, "scope": "test total",
            "scope_confirmed": True, "semantics_confirmed": True})
        with self.assertRaisesRegex(ValueError, "Synthetic"):
            create_dataset(self.engine, self.manifest(synthetic, mode="real"))

    def test_real_and_synthetic_sources_cannot_mix(self):
        real = self.ingest()
        synthetic = self.ingest(context={"synthetic": True})
        manifest = self.manifest(real)
        manifest["sources"]["systeme:inventory"] = {"import_id": synthetic["id"], "kind": "inventory_monthly"}
        # A valid second kind is needed to reach the origin check.
        with patch("app.modules.imports.service.iter_workbook", side_effect=lambda *_: iter([replace(self.row(), kind="inventory_monthly")])):
            self.path.write_bytes(uuid4().bytes)
            synthetic = import_file(self.engine, self.path, "systeme", self.storage, {"synthetic": True})
        manifest["sources"]["systeme:inventory"]["import_id"] = synthetic["id"]
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            create_dataset(self.engine, manifest)

    @unittest.skipUnless((BACKEND.parent / "Systeme electric").exists(), "Partner workbooks unavailable")
    def test_database_preview_matches_excel_without_reopening_workbooks(self):
        import json
        from app.modules.calculations.preview import preview
        from app.modules.imports.datasets import systeme_preview_sources
        root = BACKEND.parent
        folder = root / "Systeme electric"
        summary = import_file(self.engine, next(folder.glob("Товар в пути*.xlsx")), "systeme", self.storage)
        constraint = import_file(self.engine, next(folder.glob("MOQ*.xlsx")), "systeme", self.storage)
        manifest = {"name": "Real source comparison", "mode": "scenario", "acknowledge_warnings": True,
                    "sources": {f"systeme:{role}": {"import_id": summary["id"], "kind": "summary"}
                                for role in ("sales", "inventory", "inbound")}}
        manifest["sources"]["systeme:constraints"] = {"import_id": constraint["id"], "kind": "constraints"}
        dataset = create_dataset(self.engine, manifest)
        for filename in ("systeme_preview_policy.json", "systeme_robust_policy.json"):
            policy = json.loads((root / "tests/fixtures/synthetic" / filename).read_text(encoding="utf-8"))
            excel = preview(root, policy, self.folder / "excel.json")
            with patch("app.modules.calculations.preview.read", side_effect=AssertionError("Excel must not be opened")):
                persisted, _ = systeme_preview_sources(self.engine, dataset["id"])
                database = preview(root, policy, self.folder / "database.json", persisted, dataset["id"])
            self.assertEqual(excel["recommendations"], database["recommendations"])
