"""
Builds the description of the database that the NL2SQL prompt contains.

Two parts:
  1. schema.sql itself. DDL with comments is the most compact and precise way
     to explain tables, keys and the meaning of each column to an LLM.
  2. The actual values of the low-cardinality text columns (cities, customer
     types, statuses ...) plus customer/product names and the date range. With
     them the model writes `city = 'Tehran'` for a Persian "تهران" instead of
     guessing a spelling.

This is trusted code (no LLM involved), so it uses a plain read-only
connection rather than the locked-down executor.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from app.db.seed import SCHEMA_PATH

MAX_DISTINCT_VALUES = 20  # list a text column's values only if it has at most this many


def describe_database(db_path: Path) -> str:
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    lines = []
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        tables = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in tables:
            for _, column, column_type, *_ in conn.execute(f"PRAGMA table_info({table})"):
                if column_type.upper() != "TEXT" or column.endswith("_date"):
                    continue
                values = [v for (v,) in conn.execute(
                    f"SELECT DISTINCT {column} FROM {table} ORDER BY 1 LIMIT {MAX_DISTINCT_VALUES + 1}")]
                if len(values) <= MAX_DISTINCT_VALUES:
                    lines.append(f"- {table}.{column}: " + ", ".join(repr(v) for v in values))

        first, last = conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
        lines.append(f"- orders.order_date ranges from {first} to {last}")

    return f"{ddl.strip()}\n\nValues found in the data:\n" + "\n".join(lines)
