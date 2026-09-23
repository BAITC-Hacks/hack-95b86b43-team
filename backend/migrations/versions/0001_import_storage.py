# Frozen initial import schema; independent of later model edits.
from alembic import op
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("\nCREATE TABLE dataset_versions (\n\tid UUID NOT NULL, \n\tfingerprint TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\tmode TEXT NOT NULL, \n\tmanifest JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_dataset_mode CHECK (mode IN ('real','scenario')), \n\tUNIQUE (fingerprint)\n)\n\n")
    op.execute("\nCREATE TABLE import_batches (\n\tid UUID NOT NULL, \n\tidentity TEXT NOT NULL, \n\tsha256 TEXT NOT NULL, \n\tsupplier TEXT NOT NULL, \n\toriginal_name TEXT NOT NULL, \n\tstored_name TEXT NOT NULL, \n\tadapter_version TEXT NOT NULL, \n\tcontext JSONB NOT NULL, \n\tstatus TEXT NOT NULL, \n\tcounts JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_import_supplier CHECK (supplier IN ('iek','systeme')), \n\tCONSTRAINT ck_import_status CHECK (status IN ('loading','ready','needs_review','failed')), \n\tUNIQUE (identity)\n)\n\n")
    op.execute('\nCREATE TABLE dataset_sources (\n\tdataset_id UUID NOT NULL, \n\trole TEXT NOT NULL, \n\timport_id UUID NOT NULL, \n\tkind TEXT NOT NULL, \n\tPRIMARY KEY (dataset_id, role), \n\tFOREIGN KEY(dataset_id) REFERENCES dataset_versions (id), \n\tFOREIGN KEY(import_id) REFERENCES import_batches (id)\n)\n\n')
    op.execute('\nCREATE TABLE source_rows (\n\tid UUID NOT NULL, \n\timport_id UUID NOT NULL, \n\tsheet TEXT NOT NULL, \n\trow_number INTEGER NOT NULL, \n\tkind TEXT NOT NULL, \n\tproduct_code TEXT, \n\tfields JSONB NOT NULL, \n\taccepted BOOLEAN NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_source_location UNIQUE (import_id, sheet, row_number), \n\tCONSTRAINT ck_source_row_positive CHECK (row_number > 0), \n\tFOREIGN KEY(import_id) REFERENCES import_batches (id)\n)\n\n')
    op.execute('\nCREATE TABLE source_observations (\n\tsource_row_id UUID NOT NULL, \n\tfield TEXT NOT NULL, \n\tperiod DATE, \n\toccurred_at TIMESTAMP WITHOUT TIME ZONE, \n\tquantity NUMERIC, \n\tunit TEXT, \n\twarehouse TEXT, \n\tsemantics TEXT NOT NULL, \n\tPRIMARY KEY (source_row_id, field), \n\tFOREIGN KEY(source_row_id) REFERENCES source_rows (id)\n)\n\n')
    op.execute("\nCREATE TABLE validation_issues (\n\tid UUID NOT NULL, \n\timport_id UUID NOT NULL, \n\tsource_row_id UUID, \n\tseverity TEXT NOT NULL, \n\tcode TEXT NOT NULL, \n\tmessage TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_issue_severity CHECK (severity IN ('error','warning','info')), \n\tFOREIGN KEY(import_id) REFERENCES import_batches (id), \n\tFOREIGN KEY(source_row_id) REFERENCES source_rows (id)\n)\n\n")
    op.execute('CREATE INDEX ix_source_import_kind_code ON source_rows (import_id, kind, product_code)')
    op.execute('CREATE INDEX ix_observation_period ON source_observations (period)')
    op.execute('CREATE INDEX ix_issues_import ON validation_issues (import_id, severity)')

def downgrade():
    op.drop_table('validation_issues')
    op.drop_table('source_observations')
    op.drop_table('source_rows')
    op.drop_table('dataset_sources')
    op.drop_table('import_batches')
    op.drop_table('dataset_versions')
