"""Database connection helpers. Settings are read from the .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL

PROJECT_DIR = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_DIR / "sql"

load_dotenv(PROJECT_DIR / ".env")


def get_engine(database: str | None = None) -> Engine:
    """Return an SQLAlchemy engine for the project database (or another one)."""
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=database or os.getenv("PGDATABASE", "contact_center"),
    )
    return create_engine(url)


def create_database_if_missing() -> None:
    """CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT."""
    name = os.getenv("PGDATABASE", "contact_center")
    engine = get_engine("postgres").execution_options(isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
            print(f"Created database {name}")
    engine.dispose()


def run_sql_file(engine: Engine, filename: str) -> None:
    """Execute every statement of a file from the sql/ folder in one transaction."""
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
