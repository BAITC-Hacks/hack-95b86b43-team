"""Atomic, content-addressed imports. No import implicitly activates a dataset."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
from uuid import uuid4

from ...db.repositories import ImportRepository
from .adapters.common import ADAPTER_VERSION, file_hash, iter_workbook
from .profiling import dumps
from .validation import normalize_observations

STORAGE_VERSION = "1"


def import_file(engine, path: Path, supplier: str, storage: Path, context: dict | None = None):
    if supplier not in {"iek", "systeme"}:
        raise ValueError("Unknown supplier")
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        raise ValueError("An existing .xlsx file is required")
    context = dict(context or {})
    allowed = {"scope", "scope_confirmed", "semantics_confirmed", "synthetic", "snapshot_date", "inbound_year"}
    if set(context) - allowed:
        raise ValueError("Unsupported source context fields")
    context.setdefault("scope", "unconfirmed")
    context.setdefault("scope_confirmed", False)
    context.setdefault("semantics_confirmed", False)
    context.setdefault("synthetic", False)
    if any(type(context[key]) is not bool for key in ("scope_confirmed", "semantics_confirmed", "synthetic")):
        raise ValueError("Context confirmations and synthetic flag must be booleans")
    if not isinstance(context["scope"], str) or not context["scope"].strip():
        raise ValueError("A nonempty scope description is required")
    if context["scope_confirmed"] and context["scope"] == "unconfirmed":
        raise ValueError("Name the confirmed source scope")
    from datetime import date
    if context.get("snapshot_date"):
        date.fromisoformat(context["snapshot_date"])
    if context.get("inbound_year") is not None:
        if type(context["inbound_year"]) is not int or not 1900 <= context["inbound_year"] <= 9999:
            raise ValueError("Invalid inbound year")
    digest = file_hash(path)
    identity = sha256(dumps([digest, supplier, ADAPTER_VERSION, STORAGE_VERSION, context]).encode()).hexdigest()
    storage.mkdir(parents=True, exist_ok=True)
    with engine.begin() as connection:
        repository = ImportRepository(connection)
        # Also serialize source-copy creation across different contexts of the same bytes.
        repository.lock(digest)
        repository.lock(identity)
        previous = repository.find(identity)
        if previous and previous["status"] != "failed":
            return {**dict(previous), "reused": True}
        stored = storage / f"{digest}.xlsx"
        if not stored.exists():
            temporary = storage / f"{digest}.{uuid4().hex}.tmp"
            try:
                shutil.copyfile(path, temporary)
                if file_hash(temporary) != digest:
                    raise ValueError("Source changed while copying; retry")
                temporary.replace(stored)
            finally:
                temporary.unlink(missing_ok=True)
        if file_hash(stored) != digest:
            raise ValueError("Stored source checksum mismatch")
        import_id = previous["id"] if previous else str(uuid4())
        if previous:
            repository.clear_failed(import_id)
        else:
            repository.start(dict(id=import_id, identity=identity, sha256=digest, supplier=supplier,
                original_name=path.name, stored_name=stored.name, adapter_version=ADAPTER_VERSION,
                context=context, status="loading", counts={}))
        try:
            # Savepoint preserves only the failed batch metadata if parsing/writing fails.
            with connection.begin_nested():
                rows, values, diagnostics = [], [], []
                for source in iter_workbook(stored, supplier):
                    row_id = str(uuid4())
                    normalized, problems = normalize_observations(source, context)
                    accepted = bool(source.code) and source.kind not in {"unknown", "non_product", "seasonality"} and not any(p[0] == "error" for p in problems)
                    rows.append(dict(id=row_id, import_id=import_id, sheet=source.sheet,
                        row_number=source.row, kind=source.kind, product_code=source.code,
                        fields=json.loads(dumps(source.fields)), accepted=accepted))
                    values.extend(dict(source_row_id=row_id, **v) for v in normalized)
                    diagnostics.extend(dict(id=str(uuid4()), import_id=import_id, source_row_id=row_id,
                        severity=level, code=code, message=message) for level, code, message in problems)
                    if len(rows) >= 500:
                        repository.append(rows, values, diagnostics)
                        rows, values, diagnostics = [], [], []
                repository.append(rows, values, diagnostics)
                repository.reject_duplicate_keys(import_id)
                if not context["scope_confirmed"] or not context["semantics_confirmed"]:
                    repository.issue(import_id, "warning", "unconfirmed_context", "Scope and operation semantics require confirmation")
                if file_hash(stored) != digest:
                    raise ValueError("Stored source changed during import")
                repository.finish(import_id)
        except Exception:
            # Do not persist exception text: drivers may include SQL parameters or source values.
            repository.failed(import_id)
        return {**dict(repository.get(import_id)), "reused": False}
