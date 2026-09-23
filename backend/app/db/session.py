from sqlalchemy import create_engine
from ..core.config import database_url


def get_engine(url: str | None = None):
    return create_engine(url or database_url(), pool_pre_ping=True, hide_parameters=True,
                         connect_args={"connect_timeout": 10})
