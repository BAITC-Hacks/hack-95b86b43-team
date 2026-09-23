"""Import storage. Business catalog and order models are separate future migrations."""
from sqlalchemy import (MetaData, Table, Column, Text, Integer, Date, DateTime, Numeric,
                        Boolean, ForeignKey, UniqueConstraint, CheckConstraint, Index, text)
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = MetaData()

imports = Table("import_batches", metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("identity", Text, nullable=False, unique=True),
    Column("sha256", Text, nullable=False),
    Column("supplier", Text, nullable=False),
    Column("original_name", Text, nullable=False),
    Column("stored_name", Text, nullable=False),
    Column("adapter_version", Text, nullable=False),
    Column("context", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("counts", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    CheckConstraint("supplier IN ('iek','systeme')", name="ck_import_supplier"),
    CheckConstraint("status IN ('loading','ready','needs_review','failed')", name="ck_import_status"))

source_rows = Table("source_rows", metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("import_id", UUID(as_uuid=False), ForeignKey("import_batches.id"), nullable=False),
    Column("sheet", Text, nullable=False), Column("row_number", Integer, nullable=False),
    Column("kind", Text, nullable=False), Column("product_code", Text),
    Column("fields", JSONB, nullable=False), Column("accepted", Boolean, nullable=False),
    UniqueConstraint("import_id", "sheet", "row_number", name="uq_source_location"),
    CheckConstraint("row_number > 0", name="ck_source_row_positive"))
Index("ix_source_import_kind_code", source_rows.c.import_id, source_rows.c.kind, source_rows.c.product_code)

issues = Table("validation_issues", metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("import_id", UUID(as_uuid=False), ForeignKey("import_batches.id"), nullable=False),
    Column("source_row_id", UUID(as_uuid=False), ForeignKey("source_rows.id")),
    Column("severity", Text, nullable=False), Column("code", Text, nullable=False),
    Column("message", Text, nullable=False),
    CheckConstraint("severity IN ('error','warning','info')", name="ck_issue_severity"))
Index("ix_issues_import", issues.c.import_id, issues.c.severity)

# Long-form quantities preserve distinct source kinds and fields. A NULL quantity is unknown.
# No derived sales sign, stock date, warehouse allocation or confirmed shipment is invented.
observations = Table("source_observations", metadata,
    Column("source_row_id", UUID(as_uuid=False), ForeignKey("source_rows.id"), primary_key=True),
    Column("field", Text, primary_key=True),
    Column("period", Date), Column("occurred_at", DateTime(timezone=False)),
    Column("quantity", Numeric()), Column("unit", Text), Column("warehouse", Text),
    Column("semantics", Text, nullable=False))
Index("ix_observation_period", observations.c.period)

datasets = Table("dataset_versions", metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("fingerprint", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False), Column("mode", Text, nullable=False),
    Column("manifest", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    CheckConstraint("mode IN ('real','scenario')", name="ck_dataset_mode"))

dataset_sources = Table("dataset_sources", metadata,
    Column("dataset_id", UUID(as_uuid=False), ForeignKey("dataset_versions.id"), primary_key=True),
    Column("role", Text, primary_key=True),
    Column("import_id", UUID(as_uuid=False), ForeignKey("import_batches.id"), nullable=False),
    Column("kind", Text, nullable=False))
