from pathlib import Path
import os

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]


def database_url() -> str:
    load_dotenv(ROOT / ".env", override=False)
    value = os.environ.get("DATABASE_URL", "")
    if not value:
        raise ValueError("Set DATABASE_URL in the repository .env or environment")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise ValueError("This storage layer requires PostgreSQL")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def upload_dir() -> Path:
    load_dotenv(ROOT / ".env", override=False)
    value = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
    return value if value.is_absolute() else ROOT / value
