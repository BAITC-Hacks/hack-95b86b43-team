from alembic import context
from sqlalchemy import create_engine
from app.core.config import database_url
from app.db.models import metadata

config = context.config
connection = config.attributes.get("connection")


def run(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif connection is not None:
    run(connection)
else:
    engine = create_engine(database_url(), hide_parameters=True)
    with engine.connect() as connection:
        run(connection)
