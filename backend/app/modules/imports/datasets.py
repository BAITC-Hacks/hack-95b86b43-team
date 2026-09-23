"""Explicit, immutable source selection; never auto-select competing histories."""
from hashlib import sha256
from uuid import uuid4

from ...db.repositories import ImportRepository, DatasetRepository
from .profiling import dumps

ROLE_KINDS = {"sales": {"sales_monthly", "summary"}, "inventory": {"inventory_monthly", "summary"},
              "inbound": {"inbound", "summary"}, "constraints": {"constraints"}, "transactions": {"transactions"}}


def create_dataset(engine, manifest):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), dict) or not manifest["sources"]:
        raise ValueError("A nonempty sources mapping is required")
    if not manifest.get("name") or manifest.get("mode") not in {"real", "scenario"}:
        raise ValueError("Dataset name and real/scenario mode are required")
    # Only explicit true permits exclusion or acceptance of diagnostic warnings.
    partial = manifest.get("allow_partial") is True
    acknowledged = manifest.get("acknowledge_warnings") is True
    frozen = {"name": manifest["name"], "mode": manifest["mode"], "allow_partial": partial,
              "acknowledge_warnings": acknowledged, "sources": {}, "limitations": []}
    with engine.begin() as connection:
        imports = ImportRepository(connection)
        repository = DatasetRepository(connection)
        origins = set()
        for role, selection in sorted(manifest["sources"].items()):
            if not isinstance(selection, dict) or ":" not in role:
                raise ValueError("Source keys must have supplier:role format")
            supplier, purpose = role.split(":", 1)
            kind = selection.get("kind")
            if kind not in ROLE_KINDS.get(purpose, set()):
                raise ValueError(f"Unsupported source kind for {role}")
            batch = imports.get(selection.get("import_id"))
            if not batch or batch["supplier"] != supplier or batch["status"] not in {"ready", "needs_review"}:
                raise ValueError(f"Unavailable import for {role}")
            counts = batch["counts"]
            if counts["by_kind"].get(kind, {}).get("accepted", 0) == 0:
                raise ValueError(f"No accepted rows for {role}")
            if counts.get("issues", {}).get("error", 0) and not partial:
                raise ValueError("Imports with errors require allow_partial=true; rejected rows remain excluded")
            if counts.get("issues", {}).get("warning", 0) and not acknowledged:
                raise ValueError("Imports with warnings require acknowledge_warnings=true")
            context = batch["context"]
            origins.add(bool(context.get("synthetic")))
            if manifest["mode"] == "real" and context.get("synthetic"):
                raise ValueError("Synthetic sources require scenario mode")
            if manifest["mode"] == "real" and (not context.get("scope_confirmed") or not context.get("semantics_confirmed")):
                raise ValueError("Unconfirmed inputs may only be activated in scenario mode")
            frozen["sources"][role] = {"import_id": batch["id"], "kind": kind,
                "sha256": batch["sha256"], "adapter_version": batch["adapter_version"],
                "context": context, "counts": counts}
            if counts.get("issues", {}):
                frozen["limitations"].append({"role": role, "issues": counts["issues"]})
        if len(origins) > 1:
            raise ValueError("Real and synthetic sources cannot be mixed in one dataset")
        fingerprint = sha256(dumps(frozen).encode()).hexdigest()
        imports.lock(fingerprint)
        old = repository.find(fingerprint)
        if old:
            return {**dict(old), "reused": True}
        dataset_id = str(uuid4())
        repository.create(dict(id=dataset_id, fingerprint=fingerprint, name=frozen["name"],
            mode=frozen["mode"], manifest=frozen), [dict(dataset_id=dataset_id, role=role,
            import_id=selection["import_id"], kind=selection["kind"]) for role, selection in frozen["sources"].items()])
        return {**repository.get(dataset_id), "reused": False}


def systeme_preview_sources(engine, dataset_id):
    from .adapters.common import SourceRow
    with engine.connect() as connection:
        repository = DatasetRepository(connection)
        dataset = repository.get(dataset_id)
        if dataset["mode"] != "scenario":
            raise ValueError("The initial preview requires a scenario dataset")
        sources = dataset["manifest"]["sources"]
        required = {"systeme:sales", "systeme:inventory", "systeme:inbound", "systeme:constraints"}
        if not required.issubset(sources):
            raise ValueError("Preview requires explicit sales, inventory, inbound and constraints sources")
        summary = sources["systeme:sales"]
        if any(sources[role]["import_id"] != summary["import_id"] or sources[role]["kind"] != "summary"
               for role in ("systeme:sales", "systeme:inventory", "systeme:inbound")):
            raise ValueError("Initial preview supports one summary for sales, inventory and inbound")
        result = {}
        imports = ImportRepository(connection)
        for kind, role in (("summary", "systeme:sales"), ("constraints", "systeme:constraints")):
            batch = imports.get(sources[role]["import_id"])
            result[kind] = [SourceRow(batch["original_name"], batch["sha256"], "systeme", row["sheet"],
                row["row_number"], row["kind"], row["product_code"], row["fields"])
                for row in repository.hydrated_rows(dataset_id, role)]
        return result, dataset


def iek_preview_sources(engine, dataset_id):
    from .adapters.common import SourceRow
    kinds = {"sales": "sales_monthly", "inventory": "inventory_monthly",
             "inbound": "inbound", "constraints": "constraints"}
    with engine.connect() as connection:
        repository = DatasetRepository(connection)
        dataset = repository.get(dataset_id)
        if dataset["mode"] != "scenario":
            raise ValueError("IEK preview requires a scenario dataset")
        sources = dataset["manifest"]["sources"]
        result = {}
        scopes = {v["context"]["scope"] for k, v in sources.items()
                  if k.startswith("iek:") and v["context"].get("scope_confirmed")}
        if len(scopes) > 1:
            raise ValueError("IEK source scopes conflict")
        for role, kind in kinds.items():
            key = "iek:" + role
            if key not in sources or sources[key]["kind"] != kind:
                raise ValueError(f"IEK preview requires explicit {key}:{kind}")
            if sources[key]["context"].get("synthetic"):
                raise ValueError("Synthetic sources cannot be labelled as real IEK inputs")
            batch = ImportRepository(connection).get(sources[key]["import_id"])
            rows = repository.hydrated_rows(dataset_id, key) + repository.rejected_rows(dataset_id, key)
            rows.sort(key=lambda r: (r["sheet"], r["row_number"]))
            result[role] = [SourceRow(batch["original_name"], batch["sha256"], "iek", row["sheet"],
                row["row_number"], row["kind"], row["product_code"], row["fields"],
                () if row["accepted"] else ("Rejected source row",)) for row in rows]
        return result, dataset
