"""Freeze completed imports and dataset manifests at database level."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION reject_dataset_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Dataset versions are immutable'; END $$;
    CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE ON dataset_versions
      FOR EACH ROW EXECUTE FUNCTION reject_dataset_mutation();
    CREATE TRIGGER immutable_dataset_source BEFORE UPDATE OR DELETE ON dataset_sources
      FOR EACH ROW EXECUTE FUNCTION reject_dataset_mutation();

    CREATE FUNCTION check_dataset_source() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE expected jsonb;
    BEGIN
      SELECT manifest->'sources'->NEW.role INTO expected FROM dataset_versions WHERE id=NEW.dataset_id;
      IF expected IS NULL OR expected->>'import_id' <> NEW.import_id::text OR expected->>'kind' <> NEW.kind THEN
        RAISE EXCEPTION 'Dataset source differs from frozen manifest';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER dataset_source_matches BEFORE INSERT ON dataset_sources
      FOR EACH ROW EXECUTE FUNCTION check_dataset_source();

    CREATE FUNCTION freeze_import() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status IN ('ready','needs_review') THEN RAISE EXCEPTION 'Completed imports are immutable'; END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_import BEFORE UPDATE OR DELETE ON import_batches
      FOR EACH ROW EXECUTE FUNCTION freeze_import();

    CREATE FUNCTION freeze_import_child() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE payload jsonb; parent_id uuid; parent_status text;
    BEGIN
      IF TG_OP = 'DELETE' THEN payload := to_jsonb(OLD); ELSE payload := to_jsonb(NEW); END IF;
      IF TG_TABLE_NAME = 'source_observations' THEN
        SELECT import_id INTO parent_id FROM source_rows WHERE id=(payload->>'source_row_id')::uuid;
      ELSE parent_id := (payload->>'import_id')::uuid;
      END IF;
      SELECT status INTO parent_status FROM import_batches WHERE id=parent_id;
      IF parent_status IN ('ready','needs_review') THEN RAISE EXCEPTION 'Completed import records are immutable'; END IF;
      IF TG_OP = 'UPDATE' AND (to_jsonb(OLD)->>'import_id' IS DISTINCT FROM to_jsonb(NEW)->>'import_id'
          OR to_jsonb(OLD)->>'source_row_id' IS DISTINCT FROM to_jsonb(NEW)->>'source_row_id') THEN
        RAISE EXCEPTION 'Record ownership cannot change';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_source BEFORE INSERT OR UPDATE OR DELETE ON source_rows
      FOR EACH ROW EXECUTE FUNCTION freeze_import_child();
    CREATE TRIGGER immutable_observation BEFORE INSERT OR UPDATE OR DELETE ON source_observations
      FOR EACH ROW EXECUTE FUNCTION freeze_import_child();
    CREATE TRIGGER immutable_issue BEFORE INSERT OR UPDATE OR DELETE ON validation_issues
      FOR EACH ROW EXECUTE FUNCTION freeze_import_child();
    """)


def downgrade():
    for name, table in (("immutable_issue", "validation_issues"), ("immutable_observation", "source_observations"),
                        ("immutable_source", "source_rows"), ("immutable_import", "import_batches"),
                        ("dataset_source_matches", "dataset_sources"), ("immutable_dataset_source", "dataset_sources"),
                        ("immutable_dataset", "dataset_versions")):
        op.execute(f"DROP TRIGGER {name} ON {table}")
    for name in ("freeze_import_child", "freeze_import", "check_dataset_source", "reject_dataset_mutation"):
        op.execute(f"DROP FUNCTION {name}()")
