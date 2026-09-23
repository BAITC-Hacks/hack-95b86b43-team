"""All SQL for import/dataset workflows lives here."""
from uuid import uuid4
from sqlalchemy import select, insert, update, delete, func, text

from .models import imports, source_rows, observations, issues, datasets, dataset_sources


class ImportRepository:
    def __init__(self, connection):
        self.connection = connection

    def lock(self, identity):
        key = int(identity[:16], 16)
        if key >= 2 ** 63:
            key -= 2 ** 64
        self.connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def find(self, identity):
        return self.connection.execute(select(imports).where(imports.c.identity == identity)).mappings().first()

    def get(self, import_id):
        return self.connection.execute(select(imports).where(imports.c.id == import_id)).mappings().first()

    def start(self, values):
        self.connection.execute(insert(imports), values)

    def clear_failed(self, import_id):
        self.connection.execute(delete(issues).where(issues.c.import_id == import_id))
        self.connection.execute(update(imports).where(imports.c.id == import_id).values(status="loading", counts={}))

    def append(self, rows, values, diagnostics):
        if rows:
            self.connection.execute(insert(source_rows), rows)
        if values:
            self.connection.execute(insert(observations), values)
        if diagnostics:
            self.connection.execute(insert(issues), diagnostics)

    def issue(self, import_id, severity, code, message, row_id=None):
        self.connection.execute(insert(issues), dict(id=str(uuid4()), import_id=import_id,
            source_row_id=row_id, severity=severity, code=code, message=message))

    def reject_duplicate_keys(self, import_id):
        keys = self.connection.execute(select(source_rows.c.sheet, source_rows.c.kind, source_rows.c.product_code)
            .where(source_rows.c.import_id == import_id, source_rows.c.product_code.is_not(None),
                   source_rows.c.kind.not_in(["transactions", "seasonality", "non_product"]))
            .group_by(source_rows.c.sheet, source_rows.c.kind, source_rows.c.product_code)
            .having(func.count() > 1)).all()
        for sheet, kind, code in keys:
            row_ids = self.connection.execute(select(source_rows.c.id).where(
                source_rows.c.import_id == import_id, source_rows.c.sheet == sheet,
                source_rows.c.kind == kind, source_rows.c.product_code == code)).scalars().all()
            self.connection.execute(update(source_rows).where(source_rows.c.id.in_(row_ids)).values(accepted=False))
            self.connection.execute(delete(observations).where(observations.c.source_row_id.in_(row_ids)))
            for row_id in row_ids:
                self.issue(import_id, "error", "duplicate_product_key", "Repeated product key within source; all occurrences excluded", row_id)

    def finish(self, import_id):
        groups = self.connection.execute(select(source_rows.c.kind, source_rows.c.accepted, func.count())
            .where(source_rows.c.import_id == import_id).group_by(source_rows.c.kind, source_rows.c.accepted)).all()
        counts = {"rows": sum(n for _, _, n in groups), "accepted": sum(n for _, ok, n in groups if ok),
                  "by_kind": {}}
        for kind, ok, n in groups:
            group = counts["by_kind"].setdefault(kind, {"accepted": 0, "excluded": 0})
            group["accepted" if ok else "excluded"] += n
        counts["issues"] = dict(self.connection.execute(select(issues.c.severity, func.count())
            .where(issues.c.import_id == import_id).group_by(issues.c.severity)).all())
        counts["observations"] = self.connection.scalar(select(func.count()).select_from(
            observations.join(source_rows)).where(source_rows.c.import_id == import_id))
        status = "needs_review" if counts["issues"].get("error", 0) or counts["issues"].get("warning", 0) else "ready"
        self.connection.execute(update(imports).where(imports.c.id == import_id).values(status=status, counts=counts))

    def failed(self, import_id):
        self.issue(import_id, "error", "import_failed", "Import failed; no source rows were committed. Check file format and retry.")
        self.connection.execute(update(imports).where(imports.c.id == import_id).values(status="failed", counts={}))

    def list(self):
        return [dict(r) for r in self.connection.execute(select(imports).order_by(imports.c.created_at)).mappings()]

    def diagnostics(self, import_id, limit=100, offset=0):
        return [dict(r) for r in self.connection.execute(select(issues.c.id, issues.c.severity,
            issues.c.code, issues.c.message, source_rows.c.sheet, source_rows.c.row_number)
            .select_from(issues.outerjoin(source_rows)).where(issues.c.import_id == import_id)
            .order_by(issues.c.severity, source_rows.c.sheet, source_rows.c.row_number, issues.c.id)
            .limit(limit).offset(offset)).mappings()]


class DatasetRepository:
    def __init__(self, connection):
        self.connection = connection

    def find(self, fingerprint):
        return self.connection.execute(select(datasets).where(datasets.c.fingerprint == fingerprint)).mappings().first()

    def create(self, values, sources):
        self.connection.execute(insert(datasets), values)
        self.connection.execute(insert(dataset_sources), sources)

    def get(self, dataset_id):
        row = self.connection.execute(select(datasets).where(datasets.c.id == dataset_id)).mappings().first()
        if not row:
            raise ValueError("Unknown dataset")
        return dict(row)

    def rows(self, dataset_id, role, limit=100, offset=0):
        # Role explicitly selects one version and kind; never sum overlapping sources.
        statement = select(source_rows).join(dataset_sources,
            (dataset_sources.c.import_id == source_rows.c.import_id) & (dataset_sources.c.kind == source_rows.c.kind))
        return [dict(r) for r in self.connection.execute(statement.where(dataset_sources.c.dataset_id == dataset_id,
            dataset_sources.c.role == role, source_rows.c.accepted)
            .order_by(source_rows.c.sheet, source_rows.c.row_number).limit(limit).offset(offset)).mappings()]

    def hydrated_rows(self, dataset_id, role):
        """Reconstruct adapter inputs from persisted NUMERIC values, not Excel files."""
        rows = self.rows(dataset_id, role, limit=None)
        by_id = {row["id"]: row for row in rows}
        statement = select(observations).join(source_rows).join(dataset_sources,
            (dataset_sources.c.import_id == source_rows.c.import_id) & (dataset_sources.c.kind == source_rows.c.kind))
        values = self.connection.execute(statement.where(dataset_sources.c.dataset_id == dataset_id,
            dataset_sources.c.role == role, source_rows.c.accepted)).mappings()
        for value in values:
            row = by_id[value["source_row_id"]]
            row["fields"][value["field"]] = value["quantity"]
            if value["occurred_at"] is not None:
                row["fields"]["дата"] = value["occurred_at"]
        return rows

    def rejected_rows(self, dataset_id, role):
        """Diagnostic-only rows: callers must block them, never calculate from raw fields."""
        statement = select(source_rows).join(dataset_sources,
            (dataset_sources.c.import_id == source_rows.c.import_id) & (dataset_sources.c.kind == source_rows.c.kind))
        return [dict(r) for r in self.connection.execute(statement.where(
            dataset_sources.c.dataset_id == dataset_id, dataset_sources.c.role == role,
            source_rows.c.accepted.is_(False)).order_by(source_rows.c.sheet, source_rows.c.row_number)).mappings()]
